from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import now_lima
from app.models import BreakfastType, EggPrepType, Extra, ExtraCategory, Ingredient, StaffUser, Table


BREAKFASTS = [
    ("Americano", "1 jugo, 1 café, 2 huevos, 2 panes con mantequilla y mermelada.", True),
    ("Continental", "1 jugo, 1 café, 2 panes con jamón y queso, 2 huevos.", True),
    ("Dietetico", "1 jugo, 1 café, 1 ensalada de frutas, yogurt pequeño, 2 tostadas con mantequilla y mermelada.", False),
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
    "Jugos": [("Naranja", False), ("Papaya", False), ("Pina", False), ("Fresa", False), ("Mixto de la casa", False)],
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
]


def seed_database(db: Session) -> None:
    if not db.scalar(select(BreakfastType).limit(1)):
        db.add_all(
            BreakfastType(name=name, description=description, has_eggs=has_eggs, is_active=True)
            for name, description, has_eggs in BREAKFASTS
        )

    if not db.scalar(select(EggPrepType).limit(1)):
        db.add_all(EggPrepType(name=name, is_active=True) for name in EGG_PREPS)

    if not db.scalar(select(Table).limit(1)):
        db.add_all(Table(number=number, is_active=True) for number in range(1, 8))

    existing_ingredients = {name for (name,) in db.execute(select(Ingredient.name)).all()}
    missing_ingredients = [name for name in INGREDIENTS if name not in existing_ingredients]
    if missing_ingredients:
        db.add_all(Ingredient(name=name, is_active=True) for name in missing_ingredients)

    if not db.scalar(select(ExtraCategory).limit(1)):
        for category_name, extras in EXTRAS.items():
            category = ExtraCategory(name=category_name)
            db.add(category)
            db.flush()
            for name, requires_egg_prep in extras:
                db.add(
                    Extra(
                        category_id=category.id,
                        name=name,
                        requires_egg_prep=requires_egg_prep,
                        is_active=True,
                    )
                )

    if not db.scalar(select(StaffUser).limit(1)):
        db.add_all(
            [
                StaffUser(name="Cocinera turno mañana", dni="00000001", role="cook", is_active=True, created_at=now_lima()),
                StaffUser(name="Recepción principal", dni="00000002", role="receptionist", is_active=True, created_at=now_lima()),
                StaffUser(name="Gerencia Hotel Cacique", dni="00000003", role="manager", is_active=True, created_at=now_lima()),
            ]
        )

    db.commit()
