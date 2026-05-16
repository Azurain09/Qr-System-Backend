from datetime import timedelta
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from app.core.time import now_lima
from app.database import Base, SessionLocal, engine
from app.models import (
    BreakfastType,
    Cancellation,
    EggPrepType,
    Extra,
    Guest,
    Order,
    OrderDetailBreakfast,
    OrderDetailExtra,
    OrderStatusHistory,
)
from app.services.seeder import seed_database


DEMO_PREFIX = "98"
DEMO_ROWS = [
    ("Julio Rivera Vargas", "Entregado", "Habitacion", None, "203", "Americano", "Fritos", ["Naranja", "Cafe"], 12),
    ("Ana Soto Paredes", "Entregado", "Restaurante", 3, None, "Continental", "Revueltos", ["Papaya", "Con jamon y queso"], 9),
    ("Maria Quispe Rojas", "En preparacion", "Restaurante", 5, None, "Dietetico", None, ["Yogurt pequeno"], 5),
    ("Carlos Huaman Vera", "Cancelado", "Habitacion", None, "205", "Americano", "Hervidos", ["Cafe"], 7),
    ("Lucia Torres Nina", "Entregado", "Restaurante", 7, None, "Continental", "Fritos", ["Pina", "Huevos adicionales"], 15),
    ("Pedro Salas Cueva", "En camino", "Habitacion", None, "301", "Dietetico", None, ["Ensalada de frutas"], 8),
    ("Rosa Delgado Marin", "Entregado", "Restaurante", 1, None, "Americano", "Escalfados", ["Fresa"], 10),
    ("Miguel Castro Leon", "Pendiente", "Habitacion", None, "102", "Continental", "Revueltos", ["Leche"], 4),
]

CANCEL_REASONS = [
    "Pedido duplicado",
    "Cambio de decision del huesped",
    "Error en el pedido",
    "Agotamiento de insumos",
]


def get_by_name(items, name):
    return next(item for item in items if item.name == name)


def clear_demo_orders(db):
    demo_guests = db.scalars(select(Guest).where(Guest.document.like(f"{DEMO_PREFIX}%"))).all()
    demo_order_ids = [order.id for guest in demo_guests for order in guest.orders]
    for order_id in demo_order_ids:
        db.query(Cancellation).filter(Cancellation.order_id == order_id).delete()
        db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == order_id).delete()
        db.query(OrderDetailExtra).filter(OrderDetailExtra.order_id == order_id).delete()
        db.query(OrderDetailBreakfast).filter(OrderDetailBreakfast.order_id == order_id).delete()
        db.query(Order).filter(Order.id == order_id).delete()
    for guest in demo_guests:
        db.delete(guest)
    db.commit()


def seed_demo_orders():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seeded_rows = []
    try:
        seed_database(db)
        clear_demo_orders(db)
        breakfasts = db.scalars(select(BreakfastType)).all()
        eggs = db.scalars(select(EggPrepType)).all()
        extras = db.scalars(select(Extra)).all()
        start = now_lima().replace(hour=7, minute=0, second=0, microsecond=0) - timedelta(days=7)
        order_count = 40
        for index in range(order_count):
            name, status, location, table_number, room_number, breakfast_name, egg_name, extra_names, minute_offset = DEMO_ROWS[index % len(DEMO_ROWS)]
            order_time = start + timedelta(days=index // 5, minutes=(index % 5) * 38 + minute_offset)
            document = f"{DEMO_PREFIX}{index:06d}"
            guest = Guest(document=document, full_name=f"{name} {index + 1}", created_at=order_time)
            db.add(guest)
            db.flush()
            claimed_included = index % 4 != 0
            order = Order(
                guest_id=guest.id,
                delivery_location=location,
                table_number=table_number,
                room_number=room_number,
                claimed_included=claimed_included,
                status=status,
                created_at=order_time,
                expires_at=order_time + timedelta(minutes=7),
                confirmed_at=order_time + timedelta(minutes=1),
                cancelled_at=order_time + timedelta(minutes=6) if status == "Cancelado" else None,
                cancellation_reason=CANCEL_REASONS[index % len(CANCEL_REASONS)] if status == "Cancelado" else None,
            )
            db.add(order)
            db.flush()
            breakfast = get_by_name(breakfasts, breakfast_name)
            egg = get_by_name(eggs, egg_name) if egg_name else None
            db.add(OrderDetailBreakfast(order_id=order.id, breakfast_type_id=breakfast.id, egg_prep_type_id=egg.id if egg else None))
            db.add(OrderStatusHistory(order_id=order.id, status="Pendiente", created_at=order.confirmed_at))
            if status in {"En preparacion", "En camino", "Entregado"}:
                db.add(OrderStatusHistory(order_id=order.id, status="En preparacion", created_at=order.confirmed_at + timedelta(minutes=4)))
            if status in {"En camino", "Entregado"}:
                db.add(OrderStatusHistory(order_id=order.id, status="En camino", created_at=order.confirmed_at + timedelta(minutes=8)))
            if status == "Entregado":
                db.add(OrderStatusHistory(order_id=order.id, status="Entregado", created_at=order.confirmed_at + timedelta(minutes=12 + (index % 8))))
            if status == "Cancelado":
                db.add(OrderStatusHistory(order_id=order.id, status="Cancelado", created_at=order.cancelled_at))
                db.add(Cancellation(order_id=order.id, reason=order.cancellation_reason, created_at=order.cancelled_at))
            for extra_name in extra_names:
                extra = get_by_name(extras, extra_name)
                db.add(OrderDetailExtra(order_id=order.id, extra_id=extra.id, quantity=1 + (index % 2), egg_prep_type_id=egg.id if extra.requires_egg_prep and egg else None))
            seeded_rows.append(
                {
                    "order_id": order.id,
                    "document": document,
                    "guest": guest.full_name,
                    "status": status,
                    "location": location,
                    "table": table_number or "",
                    "room": room_number or "",
                    "breakfast": breakfast_name,
                    "egg_prep": egg_name or "",
                    "confirmed_at": order.confirmed_at,
                    "claimed_included": claimed_included,
                }
            )
        db.commit()
    finally:
        db.close()
    write_seed_excel(seeded_rows)
    return seeded_rows


def write_seed_excel(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Seeded demo orders"
    headers = ["order_id", "document", "guest", "status", "location", "table", "room", "breakfast", "egg_prep", "confirmed_at", "claimed_included"]
    sheet.append(headers)
    for row in rows:
        sheet.append([row[key] for key in headers])
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 20
    output = Path(__file__).resolve().parents[2] / "seeded_demo_orders.xlsx"
    workbook.save(output)
    print(f"Wrote {len(rows)} demo orders to {output}")


if __name__ == "__main__":
    seed_demo_orders()
