from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import cook_is_open, guest_is_open
from app.database import get_db
from app.models import BreakfastType, EggPrepType, Extra, Ingredient, StaffUser
from app.schemas.orders import (
    AvailabilityUpdateIn,
    ExtraCancelIn,
    OrderCreateIn,
    PurgeOrdersIn,
    StaffUserIn,
    StatusUpdateIn,
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
    list_confirmed_orders,
    purge_all_order_data,
    serialize_order,
    update_status,
    upsert_staff,
)
from app.services.websocket_manager import manager

router = APIRouter()


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


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    cleanup_expired_drafts(db)
    return serialize_order(get_order_or_404(db, order_id))


@router.get("/orders/by-document/{document}")
def get_order_by_document(document: str, db: Session = Depends(get_db)) -> dict:
    order = find_latest_order_by_document(db, document)
    return {"order": serialize_order(order) if order else None}


@router.get("/staff/{slug}/orders")
def staff_orders(slug: str, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    if not cook_is_open():
        return {"is_open": False, "message": "Sistema fuera de servicio", "orders": []}
    return {"is_open": True, "orders": list_confirmed_orders(db), "cancellation_reasons": CANCELLATION_REASONS}


@router.patch("/staff/{slug}/orders/{order_id}/status")
async def staff_update_order(slug: str, order_id: int, payload: StatusUpdateIn, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    order = update_status(db, order_id, payload.status, payload.reason)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.patch("/staff/{slug}/extras/{detail_id}/cancel")
async def staff_cancel_extra(slug: str, detail_id: int, payload: ExtraCancelIn, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
    order = cancel_extra(db, detail_id, payload.reason)
    data = serialize_order(order)
    await manager.broadcast_kitchen({"type": "orders_changed", "order": data})
    await manager.broadcast_order(order.id, {"type": "status_changed", "order": data})
    return data


@router.patch("/staff/{slug}/availability/{kind}/{item_id}")
async def update_availability(slug: str, kind: str, item_id: int, payload: AvailabilityUpdateIn, db: Session = Depends(get_db)) -> dict:
    require_slug("cook", slug)
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
    db.commit()
    await manager.broadcast_kitchen({"type": "catalog_changed"})
    await manager.broadcast_catalog({"type": "catalog_changed"})
    return serialize_catalog(db)


@router.get("/reports/{slug}/daily")
def report_daily(slug: str, date: str | None = None, db: Session = Depends(get_db)) -> dict:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return daily_report(db, date).model_dump()


@router.get("/reports/{slug}/dashboard")
def report_dashboard(slug: str, date: str | None = None, db: Session = Depends(get_db)) -> dict:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
    elif slug == settings.cook_slug:
        require_slug("cook", slug)
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return dashboard_report(db, date)


@router.get("/reports/{slug}/daily.xlsx")
def report_daily_xlsx(slug: str, date: str | None = None, db: Session = Depends(get_db)) -> StreamingResponse:
    if slug == settings.reception_slug:
        require_slug("reception", slug)
    elif slug == settings.manager_slug:
        require_slug("manager", slug)
    else:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    report = daily_report(db, date)
    output = report_to_excel(report)
    filename = f"qr-system-reporte-{report.date}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/manager/{slug}/staff")
def list_staff(slug: str, db: Session = Depends(get_db)) -> list[dict]:
    require_slug("manager", slug)
    users = db.scalars(select(StaffUser).order_by(StaffUser.name)).all()
    return [
        {"id": user.id, "name": user.name, "dni": user.dni, "role": user.role, "is_active": user.is_active}
        for user in users
    ]


@router.post("/manager/{slug}/staff")
def create_staff(slug: str, payload: StaffUserIn, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
    user = upsert_staff(db, payload)
    return {"id": user.id, "name": user.name, "dni": user.dni, "role": user.role, "is_active": user.is_active}


@router.put("/manager/{slug}/staff/{staff_id}")
def update_staff(slug: str, staff_id: int, payload: StaffUserIn, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
    user = upsert_staff(db, payload, staff_id)
    return {"id": user.id, "name": user.name, "dni": user.dni, "role": user.role, "is_active": user.is_active}


@router.post("/manager/{slug}/purge-orders")
async def purge_orders(slug: str, payload: PurgeOrdersIn, db: Session = Depends(get_db)) -> dict:
    require_slug("manager", slug)
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
