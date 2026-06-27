from dataclasses import dataclass
from datetime import time
import os
from zoneinfo import ZoneInfo


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


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
    staff_password: str = os.getenv("STAFF_PASSWORD", "Cacique2026")
    staff_token_secret: str = os.getenv("STAFF_TOKEN_SECRET", "AunNWDnpzJw2HMUz5dkdmOFAoWH31TMrT-7DWTbs10g")
    staff_token_minutes: int = int(os.getenv("STAFF_TOKEN_MINUTES", "480"))
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
    allowed_origins: list[str] = None
    allowed_origin_regex: str = os.getenv(
        "ALLOWED_ORIGIN_REGEX",
        r"https://.*\.ngrok-free\.app|https://.*\.ngrok\.app|http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+):\d+",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_origins",
            env_list(
                "ALLOWED_ORIGINS",
                [
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                    "https://qr-system-ntti.onrender.com",
                ],
            ),
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


settings = Settings()
