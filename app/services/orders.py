from collections import Counter
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.core.time import cook_is_open, guest_is_open, now_lima
from app.models import (
    BreakfastType,
    Cancellation,
    EggPrepType,
    Extra,
    ExtraCategory,
    Guest,
    Ingredient,
    Order,
    OrderDetailBreakfast,
    OrderDetailExtra,
    OrderStatusHistory,
    Report,
    StaffUser,
)
from app.schemas.orders import ExtraSelectionIn, OrderCreateIn, ReportOut, StaffUserIn


ORDER_STATUSES = ["Pendiente", "En preparación", "Entregado"]
INTERNAL_DRAFT_STATUS = "Borrador"
STATUS_ALIASES = {
    "Borrador": "Pendiente",
    "En preparacion": "En preparación",
    "En preparación": "En preparación",
    "En camino": "En preparación",
    "Cancelado": "Pendiente",
    "Pendiente": "Pendiente",
    "Entregado": "Entregado",
}
CANCELLATION_REASONS = [
    "Pedido duplicado",
    "Retiro del huesped antes de recibir el desayuno",
    "Agotamiento de insumos",
    "Error en el pedido",
    "Imposibilidad de preparacion",
    "Cambio de decision del huesped",
]


def cleanup_expired_drafts(db: Session) -> int:
    current = now_lima()
    expired = db.scalars(
        select(Order).where(Order.status == INTERNAL_DRAFT_STATUS, Order.expires_at < current)
    ).all()
    for order in expired:
        db.delete(order)
    if expired:
        db.commit()
    return len(expired)


def normalize_status(status: str) -> str:
    return STATUS_ALIASES.get(status, status)


def validate_guest_open() -> None:
    if not guest_is_open():
        raise HTTPException(status_code=403, detail="Sistema fuera de servicio")


def validate_cook_open() -> None:
    if not cook_is_open():
        raise HTTPException(status_code=403, detail="Sistema fuera de servicio")


def serialize_order(order: Order) -> dict:
    return {
        "id": order.id,
        "guest_name": order.guest.full_name,
        "document": order.guest.document,
        "delivery_location": order.delivery_location,
        "table_number": order.table_number,
        "room_number": order.room_number,
        "claimed_included": order.claimed_included,
        "status": normalize_status(order.status),
        "breakfast_type": order.breakfast_detail.breakfast_type.name,
        "egg_prep": order.breakfast_detail.egg_prep_type.name if order.breakfast_detail.egg_prep_type else None,
        "extras": [
            {
                "id": detail.id,
                "extra_id": detail.extra_id,
                "name": detail.extra.name,
                "category_name": detail.extra.category.name,
                "quantity": detail.quantity,
                "egg_prep": detail.egg_prep_type.name if detail.egg_prep_type else None,
                "is_cancelled": detail.is_cancelled,
                "cancellation_reason": detail.cancellation_reason,
            }
            for detail in order.extra_details
        ],
        "created_at": order.created_at,
        "expires_at": order.expires_at,
        "confirmed_at": order.confirmed_at,
        "cancellation_reason": order.cancellation_reason,
    }


def order_query():
    return (
        select(Order)
        .options(
            joinedload(Order.guest),
            joinedload(Order.breakfast_detail).joinedload(OrderDetailBreakfast.breakfast_type),
            joinedload(Order.breakfast_detail).joinedload(OrderDetailBreakfast.egg_prep_type),
            selectinload(Order.extra_details).joinedload(OrderDetailExtra.extra).joinedload(Extra.category),
            selectinload(Order.extra_details).joinedload(OrderDetailExtra.egg_prep_type),
        )
    )


def get_order_or_404(db: Session, order_id: int) -> Order:
    order = db.scalar(order_query().where(Order.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return order


def find_latest_order_by_document(db: Session, document: str) -> Order | None:
    cleanup_expired_drafts(db)
    if not document.isdigit() or len(document) != 8:
        raise HTTPException(status_code=422, detail="El DNI debe tener 8 digitos")
    today = now_lima().date()
    orders = db.scalars(
        order_query()
        .join(Guest)
        .where(Guest.document == document)
        .order_by(Order.created_at.desc())
    ).unique().all()
    for order in orders:
        if order.created_at.date() == today:
            return order
    return None


def list_confirmed_orders(db: Session) -> list[dict]:
    cleanup_expired_drafts(db)
    today = now_lima().date()
    orders = db.scalars(
        order_query()
        .where(Order.status != INTERNAL_DRAFT_STATUS)
        .order_by(Order.confirmed_at.asc(), Order.created_at.asc())
    ).unique().all()
    todays_orders = [
        order
        for order in orders
        if (order.confirmed_at or order.created_at).date() == today
    ]
    return [serialize_order(order) for order in todays_orders]


def create_draft_order(db: Session, payload: OrderCreateIn) -> Order:
    validate_guest_open()
    cleanup_expired_drafts(db)

    if payload.delivery_location not in ("Restaurante", "Habitacion"):
        raise HTTPException(status_code=422, detail="Completar todos los campos")
    if payload.delivery_location == "Restaurante" and payload.table_number not in range(1, 8):
        raise HTTPException(status_code=422, detail="La mesa debe ser un numero entre 1 y 7")
    if payload.delivery_location == "Habitacion":
        if not payload.room_number or not payload.room_number.isdigit() or len(payload.room_number) != 3:
            raise HTTPException(status_code=422, detail="La habitacion debe tener 3 digitos")

    breakfast = db.get(BreakfastType, payload.breakfast_type_id)
    if not breakfast or not breakfast.is_active:
        raise HTTPException(status_code=422, detail="Desayuno no disponible")
    if breakfast.has_eggs and not payload.egg_prep_type_id:
        raise HTTPException(status_code=422, detail="Completar todos los campos")
    if payload.egg_prep_type_id:
        egg_prep = db.get(EggPrepType, payload.egg_prep_type_id)
        if not egg_prep or not egg_prep.is_active:
            raise HTTPException(status_code=422, detail="Preparacion de huevo no disponible")

    guest = Guest(document=payload.document, full_name=payload.full_name, created_at=now_lima())
    db.add(guest)
    db.flush()

    order = Order(
        guest_id=guest.id,
        delivery_location=payload.delivery_location,
        table_number=payload.table_number if payload.delivery_location == "Restaurante" else None,
        room_number=payload.room_number if payload.delivery_location == "Habitacion" else None,
        claimed_included=payload.claimed_included,
        status=INTERNAL_DRAFT_STATUS,
        created_at=now_lima(),
        expires_at=now_lima() + timedelta(minutes=settings.pending_expiry_minutes),
    )
    db.add(order)
    db.flush()
    db.add(
        OrderDetailBreakfast(
            order_id=order.id,
            breakfast_type_id=payload.breakfast_type_id,
            egg_prep_type_id=payload.egg_prep_type_id,
        )
    )

    for selected in payload.extras:
        extra = db.get(Extra, selected.extra_id)
        if not extra or not extra.is_active:
            raise HTTPException(status_code=422, detail="Adicional no disponible")
        if extra.requires_egg_prep and not selected.egg_prep_type_id:
            raise HTTPException(status_code=422, detail="Completar todos los campos")
        db.add(
            OrderDetailExtra(
                order_id=order.id,
                extra_id=selected.extra_id,
                quantity=selected.quantity,
                egg_prep_type_id=selected.egg_prep_type_id,
                is_cancelled=False,
            )
        )

    db.commit()
    return get_order_or_404(db, order.id)


def confirm_order(db: Session, order_id: int) -> Order:
    cleanup_expired_drafts(db)
    order = get_order_or_404(db, order_id)
    if order.status != INTERNAL_DRAFT_STATUS:
        return order
    if order.expires_at < now_lima():
        db.delete(order)
        db.commit()
        raise HTTPException(status_code=410, detail="El pedido expiro")
    order.status = "Pendiente"
    order.confirmed_at = now_lima()
    order.history.append(OrderStatusHistory(status="Pendiente", created_at=now_lima()))
    db.commit()
    return get_order_or_404(db, order.id)


def append_order_extras(db: Session, order_id: int, extras: list[ExtraSelectionIn]) -> Order:
    validate_guest_open()
    cleanup_expired_drafts(db)
    order = get_order_or_404(db, order_id)
    if order.status == INTERNAL_DRAFT_STATUS:
        raise HTTPException(status_code=409, detail="Confirma el pedido antes de agregar mas adicionales")
    if order.status == "Entregado":
        raise HTTPException(status_code=409, detail="El pedido ya fue entregado")
    for selected in extras:
        extra = db.get(Extra, selected.extra_id)
        if not extra or not extra.is_active:
            raise HTTPException(status_code=422, detail="Adicional no disponible")
        if extra.requires_egg_prep and not selected.egg_prep_type_id:
            raise HTTPException(status_code=422, detail="Completar todos los campos")
        existing = next(
            (
                detail
                for detail in order.extra_details
                if detail.extra_id == selected.extra_id
                and detail.egg_prep_type_id == selected.egg_prep_type_id
                and not detail.is_cancelled
            ),
            None,
        )
        if existing:
            existing.quantity += selected.quantity
        else:
            db.add(
                OrderDetailExtra(
                    order_id=order.id,
                    extra_id=selected.extra_id,
                    quantity=selected.quantity,
                    egg_prep_type_id=selected.egg_prep_type_id,
                    is_cancelled=False,
                )
            )
    db.commit()
    return get_order_or_404(db, order.id)


def update_status(db: Session, order_id: int, status: str, reason: str | None = None) -> Order:
    validate_cook_open()
    status = normalize_status(status)
    if status not in ORDER_STATUSES:
        raise HTTPException(status_code=422, detail="Estado invalido")
    order = get_order_or_404(db, order_id)
    order.status = status
    order.history.append(OrderStatusHistory(status=status, created_at=now_lima()))
    db.commit()
    return get_order_or_404(db, order.id)


def cancel_extra(db: Session, detail_id: int, reason: str) -> Order:
    validate_cook_open()
    if reason not in CANCELLATION_REASONS:
        raise HTTPException(status_code=422, detail="Motivo de cancelacion invalido")
    detail = db.scalar(select(OrderDetailExtra).where(OrderDetailExtra.id == detail_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Adicional no encontrado")
    order = get_order_or_404(db, detail.order_id)
    if order.status != "Pendiente":
        raise HTTPException(status_code=409, detail="Solo se puede cancelar mientras el pedido esta pendiente")
    detail.is_cancelled = True
    detail.cancelled_at = now_lima()
    detail.cancellation_reason = reason
    db.add(Cancellation(order_id=detail.order_id, order_extra_id=detail.id, reason=reason, created_at=now_lima()))
    db.commit()
    return get_order_or_404(db, detail.order_id)


def daily_report(db: Session, date_value: str | None = None) -> ReportOut:
    cleanup_expired_drafts(db)
    report_date = date_value or now_lima().date().isoformat()
    orders = db.scalars(order_query().where(Order.status != INTERNAL_DRAFT_STATUS)).unique().all()
    filtered = [
        order
        for order in orders
        if (order.confirmed_at or order.created_at).date().isoformat() == report_date
    ]

    origin = Counter(order.delivery_location for order in filtered)
    breakfasts = Counter(order.breakfast_detail.breakfast_type.name for order in filtered)
    extras = Counter()
    peak_hours = Counter()
    cancellations = Counter()

    for order in filtered:
        event_time = order.confirmed_at or order.created_at
        peak_hours[f"{event_time.hour:02d}:00"] += 1
        if order.cancellation_reason:
            cancellations[order.cancellation_reason] += 1
        for detail in order.extra_details:
            if detail.is_cancelled:
                if detail.cancellation_reason:
                    cancellations[detail.cancellation_reason] += detail.quantity
                continue
            extras[detail.extra.name] += detail.quantity

    return ReportOut(
        date=report_date,
        total_orders=len(filtered),
        attended_by_origin=dict(origin),
        breakfast_types=dict(breakfasts),
        extras=dict(extras),
        peak_hours=dict(sorted(peak_hours.items())),
        cancellation_reasons=dict(cancellations),
    )


def dashboard_report(db: Session, date_value: str | None = None) -> dict:
    cleanup_expired_drafts(db)
    all_orders = db.scalars(order_query().where(Order.status != INTERNAL_DRAFT_STATUS)).unique().all()
    orders = [
        order
        for order in all_orders
        if not date_value or (order.confirmed_at or order.created_at).date().isoformat() == date_value
    ]
    category_names = ["Desayunos", "Bebidas", "Panes", "Huevos", "Otros"]
    status_labels = ["Completados", "En preparación"]
    status_by_category = {category: {status: 0 for status in status_labels} for category in category_names}
    category_mix = Counter()
    top_products = Counter()
    active_tables = Counter()
    orders_by_day = Counter()
    latest_cancellations = []
    completed_minutes = []

    def category_for_extra(category_name: str) -> str:
        if category_name in {"Bebidas calientes", "Jugos", "Lacteos"}:
            return "Bebidas"
        if category_name in {"Pan", "Tostadas"}:
            return "Panes"
        if category_name == "Huevos":
            return "Huevos"
        return "Otros"

    for order in orders:
        event_time = order.confirmed_at or order.created_at
        day_label = event_time.date().isoformat()
        orders_by_day[day_label] += 1
        if order.table_number:
            active_tables[f"Mesa {order.table_number}"] += 1
        order_status_group = "Completados" if order.status == "Entregado" else "En preparación"
        category_mix["Desayunos"] += 1
        status_by_category["Desayunos"][order_status_group] += 1
        top_products[order.breakfast_detail.breakfast_type.name] += 1
        if order.status == "Entregado" and order.confirmed_at:
            delivered_history = [entry for entry in order.history if entry.status == "Entregado"]
            if delivered_history:
                minutes = max(1, int((delivered_history[-1].created_at - order.confirmed_at).total_seconds() / 60))
                completed_minutes.append(minutes)
        for detail in order.extra_details:
            if detail.is_cancelled:
                continue
            mapped = category_for_extra(detail.extra.category.name)
            category_mix[mapped] += detail.quantity
            status_by_category[mapped][order_status_group] += detail.quantity
            top_products[detail.extra.name] += detail.quantity

    ordered_days = dict(sorted(orders_by_day.items())[-8:])
    return {
        "metrics": {
            "total_orders": len(orders),
            "completed_orders": sum(1 for order in orders if order.status == "Entregado"),
            "in_preparation_orders": sum(1 for order in orders if normalize_status(order.status) in {"Pendiente", "En preparación"}),
            "cancelled_orders": 0,
            "average_minutes": round(sum(completed_minutes) / len(completed_minutes)) if completed_minutes else 0,
        },
        "category_mix": dict(category_mix),
        "status_by_category": status_by_category,
        "orders_by_day": ordered_days,
        "top_products": [{"name": name, "quantity": quantity} for name, quantity in top_products.most_common(5)],
        "active_tables": [{"name": name, "orders": quantity} for name, quantity in active_tables.most_common(5)],
        "latest_cancellations": latest_cancellations[-5:],
        "date": date_value or "historico",
    }


def catalog_payload(db: Session) -> dict:
    categories = db.scalars(select(ExtraCategory).options(selectinload(ExtraCategory.extras))).unique().all()
    return {
        "is_guest_open": guest_is_open(),
        "is_cook_open": cook_is_open(),
        "breakfast_types": db.scalars(select(BreakfastType).order_by(BreakfastType.id)).all(),
        "egg_prep_types": db.scalars(select(EggPrepType).order_by(EggPrepType.id)).all(),
        "extra_categories": categories,
        "ingredients": db.scalars(select(Ingredient).order_by(Ingredient.name)).all(),
    }


def upsert_staff(db: Session, payload: StaffUserIn, staff_id: int | None = None) -> StaffUser:
    staff = db.get(StaffUser, staff_id) if staff_id else StaffUser(created_at=now_lima())
    if not staff:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    staff.name = payload.name.strip()
    staff.dni = payload.dni
    staff.role = payload.role
    staff.is_active = payload.is_active
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def purge_all_order_data(db: Session) -> dict:
    counts = {
        "cancellations": db.query(Cancellation).count(),
        "status_history": db.query(OrderStatusHistory).count(),
        "extras": db.query(OrderDetailExtra).count(),
        "breakfast_details": db.query(OrderDetailBreakfast).count(),
        "orders": db.query(Order).count(),
        "guests": db.query(Guest).count(),
        "reports": db.query(Report).count(),
    }
    db.query(Cancellation).delete()
    db.query(OrderStatusHistory).delete()
    db.query(OrderDetailExtra).delete()
    db.query(OrderDetailBreakfast).delete()
    db.query(Order).delete()
    db.query(Guest).delete()
    db.query(Report).delete()
    db.commit()
    return counts
