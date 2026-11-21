"""Conservative checks for optional local compute work; unknown readings fail closed."""
from dataclasses import dataclass
import platform

@dataclass
class GuardConfig:
    min_battery_percent: int = 35
    max_temperature_c: float = 42.0
    require_charging_for_turbo: bool = True
    require_wifi: bool = True

@dataclass
class GuardResult:
    allowed: bool
    reasons: list[str]

class HardwareGuard:
    def __init__(self, config: GuardConfig | None = None):
        self.config = config or GuardConfig()

    def check(self, battery_percent: int | None, temperature_c: float | None,
              is_charging: bool | None, is_wifi: bool | None, turbo: bool = False) -> GuardResult:
        reasons = []
        if battery_percent is None:
            reasons.append("Battery level unavailable; compute paused.")
        elif battery_percent < self.config.min_battery_percent and not is_charging:
            reasons.append(f"Battery below {self.config.min_battery_percent}%; connect power or wait.")
        if temperature_c is None:
            reasons.append("Temperature unavailable; compute paused.")
        elif temperature_c >= self.config.max_temperature_c:
            reasons.append(f"Device temperature is at or above {self.config.max_temperature_c:.0f}°C.")
        if turbo and self.config.require_charging_for_turbo and not is_charging:
            reasons.append("Turbo mode is only allowed while charging.")
        if self.config.require_wifi and is_wifi is not True:
            reasons.append("Wi-Fi connection is required.")
        return GuardResult(not reasons, reasons)

    @staticmethod
    def platform_supported() -> bool:
        return platform.system().lower() == "linux" and platform.machine().lower() in {"aarch64", "arm64"}
