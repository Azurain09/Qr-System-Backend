from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.core.time import now_lima
from app.models import BreakfastType, EggPrepType, Extra, ExtraCategory, Ingredient, StaffUser, Table


BREAKFASTS = [
    ("Americano", "1 jugo, 1 cafe, 2 huevos, 2 panes con mantequilla y mermelada.", True),
    ("Continental", "1 jugo, 1 cafe, 2 panes con jamon y queso, 2 huevos.", True),
    ("Dietetico", "1 jugo, 1 cafe, 1 ensalada de frutas, yogurt pequeno, 2 tostadas con mantequilla y mermelada.", False),
]

EGG_PREPS = ["Fritos", "Hervidos", "Revueltos", "Escalfados"]

EXTRAS = {
    "Pan": [
        ("Solo", False),
        ("Con mantequilla y mermelada", False),
        ("Solo mantequilla", False),
        ("Solo mermelada", False),
        ("Con jamon y queso", False),
        ("Solo jamon", False),
        ("Solo queso", False),
    ],
    "Jugos": [
        ("Naranja", False),
        ("Papaya", False),
        ("Pina", False),
        ("Mango", False),
        ("Fresa", False),
        ("Melon", False),
        ("Sandia", False),
        ("Surtido", False),
        ("Mixto de la casa", False),
    ],
    "Ensaladas": [("Ensalada de frutas", False), ("Ensalada fresca", False)],
    "Desayunos completos": [("Americano adicional", False), ("Continental adicional", False), ("Dietetico adicional", False)],
    "Huevos": [("Huevos adicionales", True)],
    "Bebidas calientes": [("Cafe", False), ("Leche", False)],
    "Lacteos": [("Yogurt pequeno", False), ("Yogurt grande", False)],
    "Tostadas": [
        ("Solo", False),
        ("Con mantequilla y mermelada", False),
        ("Solo mantequilla", False),
        ("Solo mermelada", False),
    ],
}

INGREDIENTS = [
    "Pan",
    "Mantequilla",
    "Mermelada",
    "Jamon",
    "Queso",
    "Huevos",
    "Cafe",
    "Leche",
    "Yogurt",
    "Fruta",
    "Naranja",
    "Papaya",
    "Pina",
    "Mango",
    "Fresa",
    "Melon",
    "Sandia",
    "Surtido",
]

DEFAULT_STAFF = [
    ("Cocinera turno manana", "00000001", "cocina", "Cocina"),
    ("Recepcion principal", "00000002", "recepcion", "Recepción"),
    ("Gerencia Hotel Cacique", "00000003", "gerencia", "Gerencia"),
]


def ensure_extra_category(db: Session, category_name: str, extras: list[tuple[str, bool]]) -> None:
    category = db.scalar(select(ExtraCategory).where(ExtraCategory.name == category_name))
    if not category:
        category = ExtraCategory(name=category_name)
        db.add(category)
        db.flush()
    existing = {name for (name,) in db.execute(select(Extra.name).where(Extra.category_id == category.id)).all()}
    for name, requires_egg_prep in extras:
        if name not in existing:
            db.add(Extra(category_id=category.id, name=name, requires_egg_prep=requires_egg_prep, is_active=True))


def seed_database(db: Session) -> None:
    existing_breakfasts = {name for (name,) in db.execute(select(BreakfastType.name)).all()}
    for name, description, has_eggs in BREAKFASTS:
        if name not in existing_breakfasts:
            db.add(BreakfastType(name=name, description=description, has_eggs=has_eggs, is_active=True))

    existing_eggs = {name for (name,) in db.execute(select(EggPrepType.name)).all()}
    for name in EGG_PREPS:
        if name not in existing_eggs:
            db.add(EggPrepType(name=name, is_active=True))

    if not db.scalar(select(Table).limit(1)):
        db.add_all(Table(number=number, is_active=True) for number in range(1, 8))

    existing_ingredients = {name for (name,) in db.execute(select(Ingredient.name)).all()}
    for name in INGREDIENTS:
        if name not in existing_ingredients:
            db.add(Ingredient(name=name, is_active=True))

    for category_name, extras in EXTRAS.items():
        ensure_extra_category(db, category_name, extras)

    existing_usernames = {username for (username,) in db.execute(select(StaffUser.username)).all()}
    existing_dnis = {dni for (dni,) in db.execute(select(StaffUser.dni)).all()}
    for name, dni, username, role in DEFAULT_STAFF:
        existing = db.scalar(select(StaffUser).where(StaffUser.dni == dni))
        if existing:
            existing.username = existing.username or username
            existing.password_hash = existing.password_hash or hash_password(settings.staff_password)
            existing.role = role
            existing.is_active = True
        elif username not in existing_usernames and dni not in existing_dnis:
            db.add(
                StaffUser(
                    name=name,
                    dni=dni,
                    username=username,
                    password_hash=hash_password(settings.staff_password),
                    role=role,
                    is_active=True,
                    created_at=now_lima(),
                )
            )

    db.commit()
