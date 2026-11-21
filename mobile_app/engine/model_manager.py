"""Local GGUF model catalogue and storage management. Downloads are explicit user actions."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import httpx

DEFAULT_MODEL_DIR = Path.home() / ".mindpool" / "models"
DEFAULT_MODEL_LIMIT = 3

@dataclass(frozen=True)
class ModelInfo:
    name: str
    filename: str
    url: str
    min_ram_gb: float
    description: str
    license_note: str = "Check the model publisher's license before use."

# URLs are intentionally blank until exact publisher assets and licenses are verified.
MODEL_CATALOGUE = (
    ModelInfo("Qwen 2.5 0.5B Instruct Q4", "qwen2.5-0.5b-instruct-q4.gguf", "", 2.0, "Very small instruction model."),
    ModelInfo("Llama 3.2 1B Instruct Q4", "llama-3.2-1b-instruct-q4.gguf", "", 3.0, "Compact instruction model."),
    ModelInfo("Qwen 2.5 1.5B Instruct Q4", "qwen2.5-1.5b-instruct-q4.gguf", "", 4.0, "Small general-purpose model."),
)

class ModelManager:
    def __init__(self, directory: Path = DEFAULT_MODEL_DIR, max_models: int = DEFAULT_MODEL_LIMIT):
        self.directory = Path(directory).expanduser()
        self.max_models = max(1, max_models)
        self.directory.mkdir(parents=True, exist_ok=True)

    def installed_models(self) -> list[Path]:
        return sorted(self.directory.glob("*.gguf"), key=lambda p: p.name.lower())

    def available_slots(self) -> int:
        return max(0, self.max_models - len(self.installed_models()))

    def get_model(self, filename: str) -> Path | None:
        if Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise ValueError("A GGUF filename without directories is required.")
        path = self.directory / filename
        return path if path.is_file() else None

    def remove_model(self, filename: str) -> bool:
        path = self.get_model(filename)
        if not path:
            return False
        path.unlink()
        return True

    async def download(self, url: str, filename: str, progress: Callable[[int, int], None] | None = None) -> Path:
        if not url.startswith("https://"):
            raise ValueError("Only HTTPS model downloads are allowed.")
        if Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise ValueError("A safe GGUF filename is required.")
        destination = self.directory / filename
        if self.available_slots() <= 0 and not destination.exists():
            raise RuntimeError(f"Model limit reached ({self.max_models}). Remove a model first.")
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", "0"))
                    received = 0
                    with temporary.open("wb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            output.write(chunk)
                            received += len(chunk)
                            if progress:
                                progress(received, total)
            temporary.replace(destination)
            return destination
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def disk_usage_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.installed_models())
