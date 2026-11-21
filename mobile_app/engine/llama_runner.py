import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx
from pydantic import BaseModel, Field


class LlamaServerConfig(BaseModel):
    binary_path: Path = Field(default_factory=lambda: Path.home() / ".mindpool" / "llama-server")
    host: str = "127.0.0.1"
    port: int = 8080
    model_path: Optional[Path] = None
    n_ctx: int = 4096
    n_gpu_layers: int = -1
    threads: int = 4
    temp: float = 0.7
    top_p: float = 0.95
    top_k: int = 40


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "local-model"
    messages: list[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_tokens: int = 2048
    stream: bool = True


class LlamaRunner:
    def __init__(self, config: Optional[LlamaServerConfig] = None):
        self.config = config or LlamaServerConfig()
        self._process: Optional[subprocess.Popen] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._base_url = f"http://{self.config.host}:{self.config.port}"

    async def ensure_binary(self) -> bool:
        configured_path = os.getenv("MINDPOOL_LLAMA_SERVER")
        if configured_path:
            self.config.binary_path = Path(configured_path).expanduser()

        if self.config.binary_path.is_file() and os.access(self.config.binary_path, os.X_OK):
            return True

        self.config.binary_path.parent.mkdir(parents=True, exist_ok=True)

        # Never install an Android executable on desktop Linux/macOS/Windows.
        download_url = os.getenv("MINDPOOL_LLAMA_SERVER_URL")
        is_android = hasattr(sys, "getandroidapilevel")
        if not download_url and is_android:
            download_url = (
                "https://github.com/ggml-org/llama.cpp/releases/download/b4721/"
                "llama-server-android-arm64"
            )
        if not download_url:
            print(
                "No compatible llama-server binary found. Install one for this OS "
                "or set MINDPOOL_LLAMA_SERVER / MINDPOOL_LLAMA_SERVER_URL.",
                file=sys.stderr,
            )
            return False

        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(download_url)
                resp.raise_for_status()
                self.config.binary_path.write_bytes(resp.content)
                self.config.binary_path.chmod(0o755)
            return True
        except Exception as e:
            print(f"Failed to download llama-server: {e}", file=sys.stderr)
            return False

    async def start(self, model_path: Optional[Path] = None) -> bool:
        if self._process and self._process.poll() is None:
            return True

        if model_path:
            self.config.model_path = model_path

        if not self.config.model_path or not self.config.model_path.exists():
            print("No valid model path provided", file=sys.stderr)
            return False

        if not await self.ensure_binary():
            return False

        cmd = [
            str(self.config.binary_path),
            "-m", str(self.config.model_path),
            "-c", str(self.config.n_ctx),
            "-ngl", str(self.config.n_gpu_layers),
            "-t", str(self.config.threads),
            "--host", self.config.host,
            "--port", str(self.config.port),
            "--temp", str(self.config.temp),
            "--top-p", str(self.config.top_p),
            "--top-k", str(self.config.top_k),
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                # Avoid blocking the inference process if its output buffer fills.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            await asyncio.sleep(2)
            if self._process.poll() is not None:
                print("llama-server exited during startup.", file=sys.stderr)
                self._process = None
                return False

            # Verify server is actually responding
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60.0)
            for _ in range(10):
                if await self.health_check():
                    return True
                await asyncio.sleep(0.5)

            print("llama-server started but health check failed", file=sys.stderr)
            await self.stop()
            return False
        except Exception as e:
            print(f"Failed to start llama-server: {e}", file=sys.stderr)
            return False

    async def stop(self) -> None:
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 40,
        max_tokens: int = 2048,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        if not self._client:
            raise RuntimeError("llama-server not running")

        req = ChatCompletionRequest(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_tokens=max_tokens,
            stream=stream,
        )

        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=req.model_dump(exclude_none=True),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                raise RuntimeError("ERR_MODEL_CAPACITY_EXHAUSTED")
            raise

    async def chat_completion_sync(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 40,
        max_tokens: int = 2048,
    ) -> str:
        result = []
        async for chunk in self.chat_completion(messages, temperature, top_p, top_k, max_tokens, stream=True):
            result.append(chunk)
        return "".join(result)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop_sync(self) -> None:
        """Synchronous stop for use in __exit__ and cleanup."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None

        if self._client:
            # Can't await in sync context, just nullify
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_sync()


async def download_model(model_url: str, dest_path: Path, progress_cb=None) -> bool:
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", model_url, follow_redirects=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total:
                            progress_cb(downloaded / total * 100)
        return True
    except Exception as e:
        print(f"Model download failed: {e}", file=sys.stderr)
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return False
