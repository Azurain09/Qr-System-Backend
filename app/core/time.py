from datetime import datetime, time

from app.core.config import settings


def now_lima() -> datetime:
    return datetime.now(settings.timezone).replace(tzinfo=None)


def is_between(value: datetime, start: time, end: time) -> bool:
    current = value.time()
    return start <= current <= end


def guest_is_open() -> bool:
    if settings.force_open_24h:
        return True
    return is_between(now_lima(), settings.guest_start, settings.guest_end)


def cook_is_open() -> bool:
    if settings.force_open_24h:
        return True
    return is_between(now_lima(), settings.cook_start, settings.cook_end)
