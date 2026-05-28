from dataclasses import dataclass
from datetime import time
import os
from zoneinfo import ZoneInfo


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "QR System - Hotel Cacique"
    database_url: str = "sqlite:///./qr_system.db"
    timezone_name: str = "America/Lima"
    guest_start: time = time(6, 0)
    guest_end: time = time(11, 0)
    cook_start: time = time(5, 30)
    cook_end: time = time(11, 0)
    pending_expiry_minutes: int = 3
    cook_slug: str = "cocina-huaca-7429"
    reception_slug: str = "recepcion-sol-3186"
    manager_slug: str = "gerencia-cacique-9051"
    force_open_24h: bool = env_flag("FORCE_OPEN_24H", False)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


settings = Settings()
