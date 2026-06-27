import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, Request, WebSocket

from app.core.config import settings


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _signature(payload: str) -> str:
    digest = hmac.new(settings.staff_token_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_staff_token(role: str) -> str:
    expires_at = int(time.time()) + settings.staff_token_minutes * 60
    payload = _b64encode(json.dumps({"role": role, "exp": expires_at}, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_signature(payload)}"


def verify_staff_token(token: str | None, role: str) -> None:
    if not token or "." not in token:
        raise HTTPException(status_code=401, detail="Acceso interno no autorizado")
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _signature(payload)):
        raise HTTPException(status_code=401, detail="Acceso interno no autorizado")
    try:
        data = json.loads(_b64decode(payload))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Acceso interno no autorizado") from exc
    if int(data.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Sesion interna expirada")
    token_role = data.get("role")
    if token_role not in {role, "manager"}:
        raise HTTPException(status_code=403, detail="Acceso interno restringido")


def require_staff_token(request: Request, role: str) -> None:
    verify_staff_token(request.headers.get("x-staff-token") or request.query_params.get("token"), role)


async def require_staff_websocket(websocket: WebSocket, role: str) -> bool:
    try:
        verify_staff_token(websocket.query_params.get("token"), role)
        return True
    except HTTPException:
        await websocket.close(code=1008)
        return False


def hash_password(password: str) -> str:
    digest = hmac.new(settings.staff_token_secret.encode("utf-8"), password.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)
