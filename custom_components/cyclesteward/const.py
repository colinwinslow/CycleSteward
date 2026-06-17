"""Constants for the CycleSteward integration."""

DOMAIN = "cyclesteward"

PLATFORMS = ["select", "sensor", "switch", "button", "time"]

# Default scheduling safety margin (ADR-0012 C), shared by the config flow and
# the watcher so the UI default and the runtime fallback never drift apart.
DEFAULT_MARGIN_S = 1800.0  # 30 min

# Default schedule times (ADR-0009), applied at setup so a fresh install has a
# live schedule without a manual edit.
DEFAULT_TARGET_FINISH_HOUR = 7
DEFAULT_TARGET_FINISH_MINUTE = 0
DEFAULT_MORNING_RESET_HOUR = 6
DEFAULT_MORNING_RESET_MINUTE = 0
