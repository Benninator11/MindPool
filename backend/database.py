import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiosqlite
from argon2 import PasswordHasher
from pydantic import BaseModel, Field


ph = PasswordHasher()


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    recovery_key: str
    cp_balance: int = 0
    max_devices: int = 3
    created_at: str = ""


@dataclass
class Device:
    id: int
    user_id: int
    device_fingerprint: str
    name: str
    last_seen: str = ""
    is_active: bool = True


@dataclass
class CPTransaction:
    id: int
    user_id: int
    amount: int
    reason: str
    created_at: str = ""


class Database:
    def __init__(self, db_path: str = "mindpool.db"):
        self.db_path = db_path
        self._pool: Optional[aiosqlite.Connection] = None

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    recovery_key TEXT UNIQUE NOT NULL,
                    cp_balance INTEGER DEFAULT 0,
                    max_devices INTEGER DEFAULT 3,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    device_fingerprint TEXT NOT NULL,
                    name TEXT NOT NULL,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, device_fingerprint)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cp_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_token TEXT UNIQUE NOT NULL,
                    device_fingerprint TEXT,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pool_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    params TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    assigned_worker_id INTEGER,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (requester_id) REFERENCES users(id),
                    FOREIGN KEY (assigned_worker_id) REFERENCES users(id)
                )
            """)
            await db.commit()

    async def close(self):
        if self._pool:
            await self._pool.close()

    @asynccontextmanager
    async def get_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            yield db

    async def create_user(self, username: str, password: str) -> tuple[User, str]:
        recovery_key = secrets.token_urlsafe(32)
        password_hash = ph.hash(password)

        async with self.get_db() as db:
            cursor = await db.execute(
                "INSERT INTO users (username, password_hash, recovery_key) VALUES (?, ?, ?)",
                (username, password_hash, recovery_key),
            )
            await db.commit()
            user_id = cursor.lastrowid

        user = User(
            id=user_id,
            username=username,
            password_hash=password_hash,
            recovery_key=recovery_key,
        )
        return user, recovery_key

    async def verify_password(self, username: str, password: str) -> Optional[User]:
        async with self.get_db() as db:
            row = await db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            )
            user_row = await row.fetchone()
            if not user_row:
                return None

            try:
                ph.verify(user_row["password_hash"], password)
            except Exception:
                return None

            return User(
                id=user_row["id"],
                username=user_row["username"],
                password_hash=user_row["password_hash"],
                recovery_key=user_row["recovery_key"],
                cp_balance=user_row["cp_balance"],
                max_devices=user_row["max_devices"],
                created_at=user_row["created_at"],
            )

    async def verify_recovery_key(self, recovery_key: str) -> Optional[User]:
        async with self.get_db() as db:
            row = await db.execute(
                "SELECT * FROM users WHERE recovery_key = ?", (recovery_key,)
            )
            user_row = await row.fetchone()
            if not user_row:
                return None

            return User(
                id=user_row["id"],
                username=user_row["username"],
                password_hash=user_row["password_hash"],
                recovery_key=user_row["recovery_key"],
                cp_balance=user_row["cp_balance"],
                max_devices=user_row["max_devices"],
                created_at=user_row["created_at"],
            )

    async def get_user(self, user_id: int) -> Optional[User]:
        async with self.get_db() as db:
            row = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user_row = await row.fetchone()
            if not user_row:
                return None
            return User(
                id=user_row["id"],
                username=user_row["username"],
                password_hash=user_row["password_hash"],
                recovery_key=user_row["recovery_key"],
                cp_balance=user_row["cp_balance"],
                max_devices=user_row["max_devices"],
                created_at=user_row["created_at"],
            )

    async def register_device(self, user_id: int, device_fingerprint: str, name: str) -> bool:
        async with self.get_db() as db:
            # Check device limit
            row = await db.execute(
                "SELECT COUNT(*) as count FROM devices WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            count_row = await row.fetchone()
            user_row = await db.execute(
                "SELECT max_devices FROM users WHERE id = ?", (user_id,)
            )
            user_data = await user_row.fetchone()
            max_devices = user_data["max_devices"] if user_data else 3

            if count_row["count"] >= max_devices:
                return False

            try:
                await db.execute(
                    "INSERT INTO devices (user_id, device_fingerprint, name) VALUES (?, ?, ?)",
                    (user_id, device_fingerprint, name),
                )
                await db.commit()
                return True
            except Exception:
                return False

    async def update_device_last_seen(self, user_id: int, device_fingerprint: str):
        async with self.get_db() as db:
            await db.execute(
                "UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE user_id = ? AND device_fingerprint = ?",
                (user_id, device_fingerprint),
            )
            await db.commit()

    async def add_cp(self, user_id: int, amount: int, reason: str) -> int:
        async with self.get_db() as db:
            await db.execute(
                "UPDATE users SET cp_balance = cp_balance + ? WHERE id = ?",
                (amount, user_id),
            )
            await db.execute(
                "INSERT INTO cp_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                (user_id, amount, reason),
            )
            await db.commit()
            row = await db.execute("SELECT cp_balance FROM users WHERE id = ?", (user_id,))
            user_row = await row.fetchone()
            return user_row["cp_balance"]

    async def spend_cp(self, user_id: int, amount: int, reason: str) -> tuple[bool, int]:
        async with self.get_db() as db:
            row = await db.execute("SELECT cp_balance FROM users WHERE id = ?", (user_id,))
            user_row = await row.fetchone()
            if not user_row or user_row["cp_balance"] < amount:
                return False, user_row["cp_balance"] if user_row else 0

            await db.execute(
                "UPDATE users SET cp_balance = cp_balance - ? WHERE id = ?",
                (amount, user_id),
            )
            await db.execute(
                "INSERT INTO cp_transactions (user_id, amount, reason) VALUES (?, ?, ?)",
                (user_id, -amount, reason),
            )
            await db.commit()
            new_balance = user_row["cp_balance"] - amount
            return True, new_balance

    async def get_cp_transactions(self, user_id: int, limit: int = 50) -> list[CPTransaction]:
        async with self.get_db() as db:
            row = await db.execute(
                "SELECT * FROM cp_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
            rows = await row.fetchall()
            return [
                CPTransaction(
                    id=r["id"],
                    user_id=r["user_id"],
                    amount=r["amount"],
                    reason=r["reason"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    async def create_session(self, user_id: int, device_fingerprint: str = None) -> str:
        import time
        session_token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 86400 * 30  # 30 days

        async with self.get_db() as db:
            await db.execute(
                "INSERT INTO sessions (user_id, session_token, device_fingerprint, expires_at) VALUES (?, ?, ?, ?)",
                (user_id, session_token, device_fingerprint, expires_at),
            )
            await db.commit()
        return session_token

    async def validate_session(self, session_token: str) -> Optional[User]:
        import time
        async with self.get_db() as db:
            row = await db.execute(
                "SELECT s.*, u.* FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.session_token = ? AND s.expires_at > ?",
                (session_token, int(time.time()))
            )
            session_row = await row.fetchone()
            if not session_row:
                return None
            return User(
                id=session_row["id"],
                username=session_row["username"],
                password_hash=session_row["password_hash"],
                recovery_key=session_row["recovery_key"],
                cp_balance=session_row["cp_balance"],
                max_devices=session_row["max_devices"],
                created_at=session_row["created_at"],
            )

    async def delete_session(self, session_token: str):
        async with self.get_db() as db:
            await db.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
            await db.commit()

    async def create_pool_job(self, requester_id: int, model_name: str, prompt: str, params: dict) -> int:
        import json
        async with self.get_db() as db:
            cursor = await db.execute(
                "INSERT INTO pool_jobs (requester_id, model_name, prompt, params) VALUES (?, ?, ?, ?)",
                (requester_id, model_name, prompt, json.dumps(params))
            )
            await db.commit()
            return cursor.lastrowid

    async def get_pending_jobs(self, worker_id: int = None) -> list[dict]:
        async with self.get_db() as db:
            if worker_id:
                row = await db.execute(
                    "SELECT * FROM pool_jobs WHERE status = 'pending' AND assigned_worker_id IS NULL ORDER BY created_at ASC LIMIT 10"
                )
            else:
                row = await db.execute(
                    "SELECT * FROM pool_jobs WHERE status = 'pending' AND assigned_worker_id IS NULL ORDER BY created_at ASC LIMIT 10"
                )
            rows = await row.fetchall()
            import json
            return [
                {
                    "id": r["id"],
                    "requester_id": r["requester_id"],
                    "model_name": r["model_name"],
                    "prompt": r["prompt"],
                    "params": json.loads(r["params"]),
                    "status": r["status"],
                }
                for r in rows
            ]

    async def assign_job(self, job_id: int, worker_id: int) -> bool:
        async with self.get_db() as db:
            cursor = await db.execute(
                "UPDATE pool_jobs SET status = 'assigned', assigned_worker_id = ? WHERE id = ? AND status = 'pending'",
                (worker_id, job_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def complete_job(self, job_id: int, result: str) -> bool:
        async with self.get_db() as db:
            cursor = await db.execute(
                "UPDATE pool_jobs SET status = 'completed', result = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (result, job_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_job(self, job_id: int) -> Optional[dict]:
        async with self.get_db() as db:
            row = await db.execute("SELECT * FROM pool_jobs WHERE id = ?", (job_id,))
            job_row = await row.fetchone()
            if not job_row:
                return None
            import json
            return {
                "id": job_row["id"],
                "requester_id": job_row["requester_id"],
                "model_name": job_row["model_name"],
                "prompt": job_row["prompt"],
                "params": json.loads(job_row["params"]),
                "status": job_row["status"],
                "assigned_worker_id": job_row["assigned_worker_id"],
                "result": job_row["result"],
            }


_db_instance: Optional[Database] = None


def get_database() -> Database:
    global _db_instance
    if _db_instance is None:
        db_path = os.getenv("DATABASE_PATH", "mindpool.db")
        _db_instance = Database(db_path)
    return _db_instance


async def init_database():
    db = get_database()
    await db.init()
