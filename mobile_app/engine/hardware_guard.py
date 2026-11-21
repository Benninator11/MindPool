"""Conservative checks for optional local compute work; unknown readings fail closed."""
from dataclasses import dataclass
import platform
from pathlib import Path
import sys

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
    def is_raspberry_pi() -> bool:
        """Return True only for Raspberry Pi devices running 64-bit Linux."""
        if platform.system().lower() != "linux":
            return False
        if platform.machine().lower() not in {"aarch64", "arm64"}:
            return False

        model_paths = (
            Path("/proc/device-tree/model"),
            Path("/sys/firmware/devicetree/base/model"),
        )
        for model_path in model_paths:
            try:
                model = model_path.read_bytes().replace(b"\x00", b"").decode(
                    "utf-8", errors="ignore"
                )
                if "raspberry pi" in model.lower():
                    return True
            except OSError:
                continue
        return False

    @staticmethod
    def platform_supported() -> bool:
        """MindPool supports Android and 64-bit Raspberry Pi OS."""
        is_android = hasattr(sys, "getandroidapilevel")
        return is_android or HardwareGuard.is_raspberry_pi()
