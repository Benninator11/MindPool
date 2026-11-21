import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from pydantic import BaseModel, Field

from backend.database import Database, CPTransaction, User, get_database, init_database


SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class RecoveryRequest(BaseModel):
    recovery_key: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    recovery_key: Optional[str] = None


class CPBalanceResponse(BaseModel):
    balance: int
    transactions: List[dict]


class PoolJobRequest(BaseModel):
    model_name: str
    prompt: str
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_tokens: int = 2048


class PoolJobResponse(BaseModel):
    job_id: int
    status: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage] = Field(..., min_length=1)
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_tokens: int = 2048
    stream: bool = True


class DeviceRegisterRequest(BaseModel):
    device_fingerprint: str
    device_name: str


security = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, device_fingerprint: str = None) -> str:
    expire = time.time() + 86400 * TOKEN_EXPIRE_DAYS
    payload = {"sub": str(user_id), "exp": expire}
    if device_fingerprint:
        payload["device"] = device_fingerprint
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Database = Depends(get_database),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Dict[str, WebSocket]] = {}
        self.worker_queues: Dict[int, asyncio.Queue] = {}
        self.job_subscriptions: Dict[int, Set[str]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, device_fingerprint: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        self.active_connections[user_id][device_fingerprint] = websocket

    def disconnect(self, user_id: int, device_fingerprint: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].pop(device_fingerprint, None)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, user_id: int, device_fingerprint: str, message: dict):
        if user_id in self.active_connections:
            ws = self.active_connections[user_id].get(device_fingerprint)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    async def broadcast_to_user(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            for ws in self.active_connections[user_id].values():
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def register_worker(self, user_id: int):
        if user_id not in self.worker_queues:
            self.worker_queues[user_id] = asyncio.Queue()

    def unregister_worker(self, user_id: int):
        self.worker_queues.pop(user_id, None)

    async def submit_job(self, job_data: dict) -> int:
        db = get_database()
        job_id = await db.create_pool_job(
            job_data["requester_id"],
            job_data["model_name"],
            job_data["prompt"],
            job_data["params"],
        )
        return job_id

    async def match_job_to_worker(self, job_id: int) -> Optional[int]:
        db = get_database()
        jobs = await db.get_pending_jobs()
        for job in jobs:
            if job["id"] == job_id:
                for worker_id in self.worker_queues.keys():
                    if worker_id != job["requester_id"]:
                        assigned = await db.assign_job(job_id, worker_id)
                        if assigned:
                            await self.worker_queues[worker_id].put(job)
                            return worker_id
        return None


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    yield
    db = get_database()
    await db.close()


app = FastAPI(title="MindPool Broker", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/register", response_model=TokenResponse)
async def register(request: RegisterRequest, db: Database = Depends(get_database)):
    if len(request.username) < 3 or len(request.username) > 32:
        raise HTTPException(status_code=400, detail="Username must be 3-32 characters")
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    try:
        user, recovery_key = await db.create_user(request.username, request.password)
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=400, detail="Username already exists")
        raise HTTPException(status_code=500, detail="Registration failed")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, recovery_key=recovery_key)


@app.post("/api/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Database = Depends(get_database)):
    user = await db.verify_password(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@app.post("/api/recovery", response_model=TokenResponse)
async def recovery(request: RecoveryRequest, db: Database = Depends(get_database)):
    user = await db.verify_recovery_key(request.recovery_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid recovery key")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@app.get("/api/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "cp_balance": user.cp_balance,
        "max_devices": user.max_devices,
    }


@app.post("/api/device/register")
async def register_device(
    request: DeviceRegisterRequest,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_database),
):
    success = await db.register_device(user.id, request.device_fingerprint, request.device_name)
    if not success:
        raise HTTPException(status_code=400, detail="Device limit reached or already registered")

    token = create_access_token(user.id, request.device_fingerprint)
    return {"access_token": token}


@app.get("/api/cp/balance", response_model=CPBalanceResponse)
async def get_cp_balance(user: User = Depends(get_current_user), db: Database = Depends(get_database)):
    transactions = await db.get_cp_transactions(user.id)
    return CPBalanceResponse(
        balance=user.cp_balance,
        transactions=[{"amount": t.amount, "reason": t.reason, "created_at": t.created_at} for t in transactions],
    )


@app.post("/api/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_database),
):
    estimated_cost = max(1, len(request.messages[-1].content) // 100)
    success, new_balance = await db.spend_cp(user.id, estimated_cost, f"Chat: {request.model}")
    if not success:
        raise HTTPException(
            status_code=402,
            detail="Insufficient CP balance",
            headers={"X-CP-Balance": str(new_balance)},
        )

    job_id = await db.create_pool_job(
        user.id,
        request.model,
        request.messages[-1].content,
        request.model_dump(exclude={"messages"}),
    )

    worker_id = await manager.match_job_to_worker(job_id)
    if not worker_id:
        refunded_balance = await db.add_cp(
            user.id, estimated_cost, f"Refund: {request.model} (no workers)"
        )
        raise HTTPException(
            status_code=503,
            detail="ERR_MODEL_CAPACITY_EXHAUSTED",
            headers={"X-CP-Balance": str(refunded_balance)},
        )

    return PoolJobResponse(job_id=job_id, status="assigned")


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: int, user: User = Depends(get_current_user), db: Database = Depends(get_database)):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["requester_id"] != user.id and job.get("assigned_worker_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return job


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = int(payload.get("sub", 0))
    device_fingerprint = payload.get("device", "unknown")

    db = get_database()
    user = await db.get_user(user_id)
    if not user:
        await websocket.close(code=4001, reason="User not found")
        return

    await manager.connect(websocket, user_id, device_fingerprint)
    await db.update_device_last_seen(user_id, device_fingerprint)

    if user_id in manager.worker_queues:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "worker_ready":
                manager.register_worker(user_id)
                await websocket.send_json({"type": "worker_registered", "user_id": user_id})

            elif msg_type == "worker_result":
                job_id = data.get("job_id")
                result = data.get("result")
                if job_id and result:
                    job = await db.get_job(job_id)
                    if job and job.get("assigned_worker_id") == user_id:
                        await db.complete_job(job_id, result)
                        await manager.broadcast_to_user(
                            job["requester_id"], {"type": "job_completed", "job_id": job_id, "result": result}
                        )
                        estimated_reward = max(1, len(result) // 50)
                        await db.add_cp(user_id, estimated_reward, f"Farm reward: job {job_id}")

            elif msg_type == "subscribe_job":
                job_id = data.get("job_id")
                if job_id:
                    if user_id not in manager.job_subscriptions:
                        manager.job_subscriptions[user_id] = set()
                    manager.job_subscriptions[user_id].add(str(job_id))

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        manager.disconnect(user_id, device_fingerprint)
        manager.unregister_worker(user_id)
        if user_id in manager.job_subscriptions:
            del manager.job_subscriptions[user_id]


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
