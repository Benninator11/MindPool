"""UI-independent controls for a user-started worker session; no hidden background work."""
from dataclasses import dataclass
from enum import Enum
try:
    from ..engine.hardware_guard import HardwareGuard, GuardResult
except ImportError:  # Running the Flet app from the mobile_app directory.
    from engine.hardware_guard import HardwareGuard, GuardResult

class FarmMode(str, Enum):
    ECO = "eco"
    BALANCED = "balanced"
    TURBO = "turbo"

@dataclass
class FarmStatus:
    running: bool = False
    mode: FarmMode = FarmMode.ECO
    message: str = "Farm mode is stopped."

class FarmController:
    def __init__(self, guard: HardwareGuard | None = None):
        self.guard = guard or HardwareGuard()
        self.status = FarmStatus()

    def start(self, mode: FarmMode, *, battery_percent: int | None, temperature_c: float | None,
              is_charging: bool | None, is_wifi: bool | None, user_confirmed: bool) -> GuardResult:
        if not user_confirmed:
            return GuardResult(False, ["Explicit user confirmation is required."])
        if self.status.running:
            return GuardResult(False, ["Farm mode is already running."])
        result = self.guard.check(battery_percent, temperature_c, is_charging, is_wifi, turbo=(mode == FarmMode.TURBO))
        if result.allowed:
            self.status = FarmStatus(True, mode, f"Farm mode active ({mode.value}).")
        return result

    def stop(self):
        self.status.running = False
        self.status.message = "Farm mode stopped by user."
