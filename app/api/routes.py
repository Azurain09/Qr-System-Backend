from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_staff_token, require_staff_token, require_staff_websocket, verify_password
from app.core.time import cook_is_open, guest_is_open
from app.database import get_db
from app.models import BreakfastType, EggPrepType, Extra, Ingredient, StaffUser
from app.schemas.orders import (
    AddExtrasIn,
    AvailabilityUpdateIn,
    ExtraCancelIn,
    OrderCreateIn,
    PurgeOrdersIn,
    StaffUserIn,
    StatusUpdateIn,
    CatalogCreateIn,
)
from app.services.excel import report_to_excel
from app.services.orders import (
    CANCELLATION_REASONS,
    cancel_extra,
    catalog_payload,
    cleanup_expired_drafts,
    confirm_order,
    create_draft_order,
    daily_report,
    dashboard_report,
    get_order_or_404,
    find_latest_order_by_document,
    append_order_extras,
    create_catalog_item,
    list_confirmed_orders,
    purge_all_order_data,
    serialize_order,
    update_status,
    upsert_staff,
)
from app.services.websocket_manager import manager

router = APIRouter()


class StaffLoginIn(BaseModel):
    username: str | None = None
    role: str
    password: str


def require_slug(role: str, slug: str) -> None:
    expected = {
        "cook": settings.cook_slug,
        "reception": settings.reception_slug,
        "manager": settings.manager_slug,
    }[role]
    if slug != expected:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")


def serialize_catalog(db: Session) -> dict:
    payload = catalog_payload(db)
    return {
        "is_guest_open": payload["is_guest_open"],
        "is_cook_open": payload["is_cook_open"],
        "breakfast_types": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "has_eggs": item.has_eggs,
                "is_active": item.is_active,
            }
            for item in payload["breakfast_types"]
        ],
        "egg_prep_types": [
            {"id": item.id, "name": item.name, "is_active": item.is_active}
            for item in payload["egg_prep_types"]
        ],
        "extra_categories": [
            {
                "id": category.id,
                "name": category.name,
                "extras": [
                    {
                        "id": extra.id,
                        "name": extra.name,
                        "category_id": category.id,
                        "category_name": category.name,
                        "requires_egg_prep": extra.requires_egg_prep,
                        "is_active": extra.is_active,
                    }
                    for extra in category.extras
                ],
            }
            for category in payload["extra_categories"]
        ],
        "ingredients": [
            {"id": item.id, "name": item.name, "is_active": item.is_active}
            for item in payload["ingredients"]
        ],
    }


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "guest_open": guest_is_open(),
        "cook_open": cook_is_open(),
        "timezone": settings.timezone_name,
        "links": {
            "cook": f"/{settings.cook_slug}",
            "reception": f"/{settings.reception_slug}",
            "manager": f"/{settings.manager_slug}",
        },
    }


@router.post("/auth/staff")
def staff_login(payload: StaffLoginIn, db: Session = Depends(get_db)) -> dict:
    if payload.role not in {"cook", "reception", "manager"}:
        raise HTTPException(status_code=422, detail="Rol interno invalido")
    role_names = {
        "cook": {"Cocina", "cook"},
        "reception": {"Recepción", "Recepcion", "reception", "receptionist"},
        "manager": {"Gerencia", "manager"},
    }
    default_usernames = {
        "cook": "cocina",
        "reception": "recepcion",
        "manager": "gerencia",
    }
    username = (payload.username or default_usernames[payload.role]).strip().lower()
    user = db.scalar(select(StaffUser).where(StaffUser.username == username))
    if not user or not user.is_active or user.role not in role_names[payload.role]:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    if not verify_password(payload.password, user.password_hash or ""):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return {
        "token": create_staff_token(payload.role),
        "role": payload.role,
        "expires_in_minutes": settings.staff_token_minutes,
    }


@router.get("/catalog")
def get_catalog(db: Session = Depends(get_db)) -> dict:
    cleanup_expired_drafts(db)
    return serialize_catalog(db)


@router.post("/orders")
def create_order(payload: OrderCreateIn, db: Session = Depends(get_db)) -> dict:
    order = create_draft_order(db, payload)
    return serialize_order(order)


@router.post("/orders/{order_id}/confirm")
async def confirm(order_id: int, db: Session = Depends(get_db)) -> dict:
    order = confirm_order(db, order_id)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.post("/orders/{order_id}/extras")
async def add_order_extras(order_id: int, payload: AddExtrasIn, db: Session = Depends(get_db)) -> dict:
    order = append_order_extras(db, order_id, payload.extras)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    cleanup_expired_drafts(db)
    return serialize_order(get_order_or_404(db, order_id))


@router.get("/orders/by-document/{document}")
def get_order_by_document(document: str, db: Session = Depends(get_db)) -> dict:
    order = find_latest_order_by_document(db, document)
    return {"order": serialize_order(order) if order else None}


@router.get("/staff/{slug}/orders")
def staff_orders(slug: str, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    require_staff_token(request, "cook")
    if not cook_is_open():
        return {"is_open": False, "message": "Sistema fuera de servicio", "orders": []}
    return {"is_open": True, "orders": list_confirmed_orders(db), "cancellation_reasons": CANCELLATION_REASONS}


@router.patch("/staff/{slug}/orders/{order_id}/status")
async def staff_update_order(slug: str, order_id: int, payload: StatusUpdateIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    require_staff_token(request, "cook")
    order = update_status(db, order_id, payload.status, payload.reason)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.patch("/staff/{slug}/extras/{detail_id}/cancel")
async def staff_cancel_extra(slug: str, detail_id: int, payload: ExtraCancelIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    require_staff_token(request, "cook")
    order = cancel_extra(db, detail_id, payload.reason)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.patch("/staff/{slug}/availability/{kind}/{item_id}")
async def update_availability(slug: str, kind: str, item_id: int, payload: AvailabilityUpdateIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    require_staff_token(request, "cook")
    if not cook_is_open():
        raise HTTPException(status_code=403, detail="Sistema fuera de servicio")
    model_map = {
        "breakfast": BreakfastType,
        "egg": EggPrepType,
        "extra": Extra,
        "ingredient": Ingredient,
    }
    model = model_map.get(kind)
    if not model:
        raise HTTPException(status_code=422, detail="Tipo invalido")
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    item.is_active = payload.is_active
    if kind in {"extra", "ingredient"}:
        linked_name = item.name
        if kind == "extra":
            linked_ingredient = db.scalar(select(Ingredient).where(Ingredient.name == linked_name))
            if linked_ingredient:
                linked_ingredient.is_active = payload.is_active
        else:
            linked_extras = db.scalars(select(Extra).where(Extra.name == linked_name)).all()
            for linked_extra in linked_extras:
                linked_extra.is_active = payload.is_active
    db.commit()
    await manager.broadcast_kitchen({"type": "catalog_changed"})
    await manager.broadcast_catalog({"type": "catalog_changed"})
    return serialize_catalog(db)


@router.post("/staff/{slug}/catalog-items")
async def staff_create_catalog_item(slug: str, payload: CatalogCreateIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    require_staff_token(request, "cook")
    result = create_catalog_item(db, payload)
    await manager.broadcast_kitchen({"type": "catalog_changed"})
    await manager.broadcast_catalog({"type": "catalog_changed"})
    return result


@router.get("/reports/{slug}/daily")
def report_daily(
    slug: str,
    request: Request,
    date: str | None = None,
    period: str = "daily",
    consumption_type: str = "all",
    db: Session = Depends(get_db),
) -> dict:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
        require_staff_token(request, "reception")
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
        require_staff_token(request, "manager")
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return daily_report(db, date, period, consumption_type).model_dump()


@router.get("/reports/{slug}/dashboard")
def report_dashboard(
    slug: str,
    request: Request,
    date: str | None = None,
    period: str = "daily",
    consumption_type: str = "all",
    db: Session = Depends(get_db),
) -> dict:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
        require_staff_token(request, "reception")
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
        require_staff_token(request, "manager")
    elif slug == settings.cook_slug:
        require_slug("cook", slug)
        require_staff_token(request, "cook")
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return dashboard_report(db, date, period, consumption_type)


@router.get("/reports/{slug}/daily.xlsx")
def report_daily_xlsx(
    slug: str,
    request: Request,
    date: str | None = None,
    period: str = "daily",
    consumption_type: str = "all",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
        require_staff_token(request, "reception")
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
        require_staff_token(request, "manager")
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    report = daily_report(db, date, period, consumption_type)
    output = report_to_excel(report)
    filename = f"qr-system-reporte-{report.date}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/manager/{slug}/staff")
def list_staff(slug: str, request: Request, db: Session = Depends(get_db)) -> list[dict]:
    require_slug("manager", slug)
    require_staff_token(request, "manager")
    users = db.scalars(select(StaffUser).order_by(StaffUser.name)).all()
    return [
        {"id": user.id, "name": user.name, "dni": user.dni, "username": user.username, "role": user.role, "is_active": user.is_active}
        for user in users
    ]


@router.post("/manager/{slug}/staff")
def create_staff(slug: str, payload: StaffUserIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
    require_staff_token(request, "manager")
    user = upsert_staff(db, payload)
    return {"id": user.id, "name": user.name, "dni": user.dni, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.put("/manager/{slug}/staff/{staff_id}")
def update_staff(slug: str, staff_id: int, payload: StaffUserIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
    require_staff_token(request, "manager")
    user = upsert_staff(db, payload, staff_id)
    return {"id": user.id, "name": user.name, "dni": user.dni, "username": user.username, "role": user.role, "is_active": user.is_active}


@router.post("/manager/{slug}/purge-orders")
async def purge_orders(slug: str, payload: PurgeOrdersIn, request: Request, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
    require_staff_token(request, "manager")
    if payload.confirmation_phrase != "ELIMINAR PEDIDOS":
        raise HTTPException(status_code=422, detail="Frase de confirmacion invalida")
    counts = purge_all_order_data(db)
    await manager.broadcast_kitchen({"type": "orders_changed"})
    return {"ok": True, "deleted": counts}


@router.websocket("/ws/kitchen/{slug}")
async def kitchen_ws(websocket: WebSocket, slug: str):
    if slug != settings.cook_slug:
        await websocket.close(code=1008)
        return
    if not await require_staff_websocket(websocket, "cook"):
        return
    await manager.connect_kitchen(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_kitchen(websocket)


@router.websocket("/ws/orders/{order_id}")
async def order_ws(websocket: WebSocket, order_id: int):
    await manager.connect_order(order_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_order(order_id, websocket)


@router.websocket("/ws/catalog")
async def catalog_ws(websocket: WebSocket):
    await manager.connect_catalog(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_catalog(websocket)
