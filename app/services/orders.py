from collections import Counter
from datetime import date, timedelta
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.core.time import cook_is_open, guest_is_open, now_lima
from app.core.security import hash_password
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
from app.schemas.orders import CatalogCreateIn, ExtraSelectionIn, OrderCreateIn, ReportOut, StaffUserIn


ORDER_STATUSES = ["Pendiente", "En preparación", "Entregado"]
INTERNAL_DRAFT_STATUS = "Borrador"
STATUS_ALIASES = {
    "Borrador": "Pendiente",
    "En preparacion": "En preparación",
    "En preparación": "En preparación",
    "En camino": "En preparación",
    "Cancelado": "Cancelado",
    "Pendiente": "Pendiente",
    "Entregado": "Entregado",
}
CANCELLATION_REASONS = [
    "Solicitud del huésped",
    "Razón operativa",
]
EXTRA_PRICES = {
    "Solo": 2,
    "Con mantequilla y mermelada": 4,
    "Solo mantequilla": 3,
    "Solo mermelada": 3,
    "Con jamon y queso": 6,
    "Solo jamon": 4,
    "Solo queso": 4,
    "Naranja": 6,
    "Papaya": 6,
    "Pina": 6,
    "Mango": 6,
    "Fresa": 7,
    "Melon": 6,
    "Sandia": 6,
    "Surtido": 8,
    "Mixto de la casa": 8,
    "Ensalada de frutas": 10,
    "Ensalada fresca": 9,
    "Americano adicional": 18,
    "Continental adicional": 18,
    "Dietetico adicional": 18,
    "Huevos adicionales": 8,
    "Cafe": 5,
    "Leche": 5,
    "Yogurt pequeno": 6,
    "Yogurt grande": 9,
}


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
    try:
        included_drinks = json.loads(order.included_drinks_json or "[]")
    except json.JSONDecodeError:
        included_drinks = []
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
        "cancelled_at": order.cancelled_at,
        "cancellation_reason": order.cancellation_reason,
        "included_drinks": included_drinks,
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
            selectinload(Order.history),
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
    current = now_lima()
    today = current.date()
    orders = db.scalars(
        order_query()
        .where(Order.status != INTERNAL_DRAFT_STATUS)
        .order_by(Order.confirmed_at.desc(), Order.created_at.desc())
    ).unique().all()

    def delivered_more_than_20_seconds_ago(order: Order) -> bool:
        if order.status != "Entregado":
            return False
        delivered_history = sorted(
            (entry for entry in order.history if entry.status == "Entregado"),
            key=lambda entry: entry.created_at,
        )
        return bool(delivered_history and (current - delivered_history[-1].created_at).total_seconds() >= 20)

    todays_orders = [
        order
        for order in orders
        if (order.confirmed_at or order.created_at).date() == today
        and not delivered_more_than_20_seconds_ago(order)
    ]
    return [serialize_order(order) for order in todays_orders]


def create_draft_order(db: Session, payload: OrderCreateIn) -> Order:
    validate_guest_open()
    cleanup_expired_drafts(db)

    if payload.delivery_location not in ("Restaurante", "Habitacion"):
        raise HTTPException(status_code=422, detail="Completar todos los campos")
    if payload.delivery_location == "Restaurante" and payload.table_number not in range(1, 8):
        raise HTTPException(status_code=422, detail="La mesa debe ser un número entre 1 y 7")
    if payload.delivery_location == "Habitacion":
        if not payload.room_number or not payload.room_number.isdigit() or len(payload.room_number) != 3:
            raise HTTPException(status_code=422, detail="La habitación debe tener 3 dígitos")

    breakfast = db.get(BreakfastType, payload.breakfast_type_id)
    if not breakfast or not breakfast.is_active:
        raise HTTPException(status_code=422, detail="Desayuno no disponible")
    if breakfast.has_eggs and not payload.egg_prep_type_id:
        raise HTTPException(status_code=422, detail="Completar todos los campos")
    if payload.egg_prep_type_id:
        egg_prep = db.get(EggPrepType, payload.egg_prep_type_id)
        if not egg_prep or not egg_prep.is_active:
            raise HTTPException(status_code=422, detail="Preparacion de huevo no disponible")

    drink_quantity = sum(drink.quantity for drink in payload.included_drinks)
    if not 1 <= drink_quantity <= 2:
        raise HTTPException(status_code=422, detail="Debe seleccionar entre 1 y 2 bebidas incluidas")
    juice_category = db.scalar(select(ExtraCategory).where(ExtraCategory.name == "Jugos"))
    active_juice_names = {extra.name for extra in (juice_category.extras if juice_category else []) if extra.is_active}
    for drink in payload.included_drinks:
        if drink.kind == "juice":
            ingredient = db.scalar(select(Ingredient).where(Ingredient.name == drink.name))
            if drink.name not in active_juice_names or not ingredient or not ingredient.is_active:
                raise HTTPException(status_code=422, detail="Jugo no disponible")
        if drink.kind == "coffee":
            required_ingredients = ["Cafe", "Leche"] if "Leche" in drink.name else ["Cafe"]
            if any(db.scalar(select(Ingredient).where(Ingredient.name == name, Ingredient.is_active == True)) is None for name in required_ingredients):
                raise HTTPException(status_code=422, detail="Cafe no disponible")

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
        included_drinks_json=json.dumps([drink.model_dump() for drink in payload.included_drinks], ensure_ascii=False),
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
    order.status = "En preparación"
    order.confirmed_at = now_lima()
    order.history.append(OrderStatusHistory(status="En preparación", created_at=now_lima()))
    db.commit()
    return get_order_or_404(db, order.id)


def append_order_extras(db: Session, order_id: int, extras: list[ExtraSelectionIn]) -> Order:
    validate_guest_open()
    cleanup_expired_drafts(db)
    order = get_order_or_404(db, order_id)
    if order.status == INTERNAL_DRAFT_STATUS:
        raise HTTPException(status_code=409, detail="Confirma el pedido antes de agregar más adicionales")
    if order.status == "Cancelado":
        raise HTTPException(status_code=409, detail="El pedido fue cancelado")
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
    if status == "Cancelado":
        order = get_order_or_404(db, order_id)
        if order.status == "Cancelado":
            return order
        if not reason:
            raise HTTPException(status_code=422, detail="Motivo de cancelación inválido")
        order.status = "Cancelado"
        order.cancelled_at = now_lima()
        order.cancellation_reason = reason
        order.history.append(OrderStatusHistory(status="Cancelado", created_at=now_lima()))
        db.add(Cancellation(order_id=order.id, reason=reason, created_at=now_lima()))
        db.commit()
        return get_order_or_404(db, order.id)

    status = normalize_status(status)
    if status not in ORDER_STATUSES:
        raise HTTPException(status_code=422, detail="Estado invalido")
    order = get_order_or_404(db, order_id)
    if order.status == "Cancelado":
        raise HTTPException(status_code=409, detail="El pedido fue cancelado")
    order.status = status
    order.history.append(OrderStatusHistory(status=status, created_at=now_lima()))
    db.commit()
    return get_order_or_404(db, order.id)


def cancel_extra(db: Session, detail_id: int, reason: str) -> Order:
    validate_cook_open()
    if reason not in CANCELLATION_REASONS:
        raise HTTPException(status_code=422, detail="Motivo de cancelación inválido")
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


REPORT_PERIOD_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 15,
    "monthly": 30,
    "quarterly": 90,
}

REPORT_CONSUMPTION_TYPES = {"all", "included", "extras"}


def report_date_range(date_value: str | None = None, period: str = "daily") -> tuple[date, date, str]:
    end_date = date.fromisoformat(date_value) if date_value else now_lima().date()
    days = REPORT_PERIOD_DAYS.get(period, REPORT_PERIOD_DAYS["daily"])
    start_date = end_date - timedelta(days=days - 1)
    label = end_date.isoformat() if days == 1 else f"{start_date.isoformat()} a {end_date.isoformat()}"
    return start_date, end_date, label


def orders_in_report_range(orders: list[Order], date_value: str | None = None, period: str = "daily") -> tuple[list[Order], str]:
    start_date, end_date, label = report_date_range(date_value, period)
    return [
        order
        for order in orders
        if start_date <= (order.confirmed_at or order.created_at).date() <= end_date
    ], label


def order_has_active_extras(order: Order) -> bool:
    return any(not detail.is_cancelled for detail in order.extra_details)


def filter_orders_by_consumption(orders: list[Order], consumption_type: str = "all") -> list[Order]:
    if consumption_type == "extras":
        return [order for order in orders if order_has_active_extras(order)]
    return orders


def daily_report(db: Session, date_value: str | None = None, period: str = "daily", consumption_type: str = "all") -> ReportOut:
    cleanup_expired_drafts(db)
    if consumption_type not in REPORT_CONSUMPTION_TYPES:
        consumption_type = "all"
    orders = db.scalars(order_query().where(Order.status != INTERNAL_DRAFT_STATUS)).unique().all()
    ranged_orders, report_date = orders_in_report_range(orders, date_value, period)
    filtered = filter_orders_by_consumption(ranged_orders, consumption_type)

    origin = Counter(order.delivery_location for order in filtered)
    breakfasts = Counter()
    extras = Counter()
    extra_details: list[dict] = []
    peak_hours = Counter()
    cancellations = Counter()

    for order in filtered:
        event_time = order.confirmed_at or order.created_at
        peak_hours[f"{event_time.hour:02d}:00"] += 1
        if order.cancellation_reason:
            cancellations[order.cancellation_reason] += 1
        if consumption_type in {"all", "included"}:
            breakfasts[order.breakfast_detail.breakfast_type.name] += 1
        for detail in order.extra_details:
            if detail.is_cancelled:
                if detail.cancellation_reason:
                    cancellations[detail.cancellation_reason] += detail.quantity
                continue
            if consumption_type == "included":
                continue
            extras[detail.extra.name] += detail.quantity
            unit_price = EXTRA_PRICES.get(detail.extra.name, 0)
            extra_details.append(
                {
                    "guest_name": order.guest.full_name,
                    "document": order.guest.document,
                    "extra_name": detail.extra.name,
                    "quantity": detail.quantity,
                    "unit_price": unit_price,
                    "total": unit_price * detail.quantity,
                }
            )

    return ReportOut(
        date=report_date,
        total_orders=len(filtered),
        attended_by_origin=dict(origin),
        breakfast_types=dict(breakfasts),
        extras=dict(extras),
        extra_details=extra_details,
        peak_hours=dict(sorted(peak_hours.items())),
        cancellation_reasons=dict(cancellations),
    )


def dashboard_report(db: Session, date_value: str | None = None, period: str = "daily", consumption_type: str = "all") -> dict:
    cleanup_expired_drafts(db)
    if consumption_type not in REPORT_CONSUMPTION_TYPES:
        consumption_type = "all"
    all_orders = db.scalars(order_query().where(Order.status != INTERNAL_DRAFT_STATUS)).unique().all()
    ranged_orders, report_date = orders_in_report_range(all_orders, date_value, period)
    orders = filter_orders_by_consumption(ranged_orders, consumption_type)
    category_names = ["Desayunos", "Bebidas", "Panes", "Huevos", "Otros"]
    status_labels = ["Completados", "En preparación"]
    status_by_category = {category: {status: 0 for status in status_labels} for category in category_names}
    category_mix = Counter()
    top_products = Counter()
    active_tables = Counter()
    orders_by_hour = Counter()
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
        orders_by_hour[f"{event_time.hour:02d}:00"] += 1
        if order.table_number:
            active_tables[f"Mesa {order.table_number}"] += 1
        order_status_group = "Completados" if order.status == "Entregado" else "En preparación"
        if consumption_type in {"all", "included"}:
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
            if consumption_type == "included":
                continue
            mapped = category_for_extra(detail.extra.category.name)
            category_mix[mapped] += detail.quantity
            status_by_category[mapped][order_status_group] += detail.quantity
            top_products[detail.extra.name] += detail.quantity

    ordered_hours = dict(sorted(orders_by_hour.items()))
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
        "orders_by_hour": ordered_hours,
        "top_products": [{"name": name, "quantity": quantity} for name, quantity in top_products.most_common(5)],
        "active_tables": [{"name": name, "orders": quantity} for name, quantity in active_tables.most_common(5)],
        "latest_cancellations": latest_cancellations[-5:],
        "date": report_date,
        "period": period,
        "consumption_type": consumption_type,
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
    staff.username = payload.username
    if payload.password:
        staff.password_hash = hash_password(payload.password)
    elif not staff.password_hash:
        staff.password_hash = hash_password(settings.staff_password)
    staff.role = payload.role
    staff.is_active = payload.is_active
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def create_catalog_item(db: Session, payload: CatalogCreateIn) -> dict:
    validate_cook_open()
    name = payload.name
    if payload.kind in {"juice", "ingredient", "supply"}:
        item = db.scalar(select(Ingredient).where(Ingredient.name == name))
        if item:
            item.is_active = True
        else:
            item = Ingredient(name=name, is_active=True)
            db.add(item)
        if payload.kind == "juice":
            category = db.scalar(select(ExtraCategory).where(ExtraCategory.name == "Jugos"))
            if not category:
                category = ExtraCategory(name="Jugos")
                db.add(category)
                db.flush()
            if not db.scalar(select(Extra).where(Extra.category_id == category.id, Extra.name == name)):
                db.add(Extra(category_id=category.id, name=name, requires_egg_prep=False, is_active=True))
    elif payload.kind == "egg":
        item = db.scalar(select(EggPrepType).where(EggPrepType.name == name))
        if item:
            item.is_active = True
        else:
            db.add(EggPrepType(name=name, is_active=True))
    else:
        category_name = "Pan" if payload.kind == "bread" else "Ensaladas"
        category = db.scalar(select(ExtraCategory).where(ExtraCategory.name == category_name))
        if not category:
            category = ExtraCategory(name=category_name)
            db.add(category)
            db.flush()
        item = db.scalar(select(Extra).where(Extra.category_id == category.id, Extra.name == name))
        if item:
            item.is_active = True
        else:
            db.add(Extra(category_id=category.id, name=name, requires_egg_prep=False, is_active=True))
    db.commit()
    return {"ok": True}


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
