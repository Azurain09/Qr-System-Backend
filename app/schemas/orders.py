from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ExtraSelectionIn(BaseModel):
    extra_id: int
    quantity: int = Field(ge=1, le=20)
    egg_prep_type_id: int | None = None


class DrinkSelectionIn(BaseModel):
    kind: str
    name: str
    quantity: int = Field(ge=1, le=2)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"juice", "coffee"}:
            raise ValueError("Tipo de bebida invalido")
        return value

    @field_validator("name")
    @classmethod
    def validate_drink_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Bebida invalida")
        return value


class OrderCreateIn(BaseModel):
    document: str
    full_name: str
    delivery_location: str
    table_number: int | None = None
    room_number: str | None = None
    claimed_included: bool
    breakfast_type_id: int
    egg_prep_type_id: int | None = None
    included_drinks: list[DrinkSelectionIn] = []
    extras: list[ExtraSelectionIn] = []

    @field_validator("document")
    @classmethod
    def validate_document(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 8:
            raise ValueError("Documento invalido")
        return value

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Completar todos los campos")
        return value.strip()


class ConfirmOrderIn(BaseModel):
    order_id: int


class AddExtrasIn(BaseModel):
    extras: list[ExtraSelectionIn]


class StatusUpdateIn(BaseModel):
    status: str
    reason: str | None = None


class ExtraCancelIn(BaseModel):
    reason: str


class AvailabilityUpdateIn(BaseModel):
    is_active: bool


class StaffUserIn(BaseModel):
    name: str
    dni: str
    username: str
    password: str | None = None
    role: str
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_staff_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if len(value) < 3 or any(character.isdigit() for character in value):
            raise ValueError("Ingrese correctamente el nombre y los apellidos")
        return value

    @field_validator("dni")
    @classmethod
    def validate_staff_dni(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 8:
            raise ValueError("El DNI debe contener 8 dígitos")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) < 4 or not value.replace("_", "").isalnum():
            raise ValueError("Ingrese un usuario valido")
        return value

    @field_validator("role")
    @classmethod
    def validate_staff_role(cls, value: str) -> str:
        allowed_roles = {"Cocina", "Recepción", "Gerencia"}
        if value not in allowed_roles:
            raise ValueError("Seleccione un rol válido")
        return value


class CatalogCreateIn(BaseModel):
    kind: str
    name: str

    @field_validator("kind")
    @classmethod
    def validate_catalog_kind(cls, value: str) -> str:
        allowed = {"juice", "egg", "bread", "salad", "ingredient", "supply"}
        if value not in allowed:
            raise ValueError("Tipo de opcion invalido")
        return value

    @field_validator("name")
    @classmethod
    def validate_catalog_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if len(value) < 3:
            raise ValueError("Ingrese un nombre valido")
        return value


class PurgeOrdersIn(BaseModel):
    confirmation_phrase: str


class CatalogItemOut(BaseModel):
    id: int
    name: str
    is_active: bool


class BreakfastOut(CatalogItemOut):
    description: str
    has_eggs: bool


class ExtraOut(CatalogItemOut):
    category_id: int
    category_name: str
    requires_egg_prep: bool


class ExtraCategoryOut(BaseModel):
    id: int
    name: str
    extras: list[ExtraOut]


class CatalogOut(BaseModel):
    is_guest_open: bool
    is_cook_open: bool
    breakfast_types: list[BreakfastOut]
    egg_prep_types: list[CatalogItemOut]
    extra_categories: list[ExtraCategoryOut]
    ingredients: list[CatalogItemOut]


class OrderExtraOut(BaseModel):
    id: int
    extra_id: int
    name: str
    category_name: str
    quantity: int
    egg_prep: str | None
    is_cancelled: bool
    cancellation_reason: str | None


class OrderOut(BaseModel):
    id: int
    guest_name: str
    document: str
    delivery_location: str
    table_number: int | None
    room_number: str | None
    claimed_included: bool
    status: str
    breakfast_type: str
    egg_prep: str | None
    extras: list[OrderExtraOut]
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None


class ReportOut(BaseModel):
    date: str
    total_orders: int
    attended_by_origin: dict[str, int]
    breakfast_types: dict[str, int]
    extras: dict[str, int]
    extra_details: list[dict]
    peak_hours: dict[str, int]
    cancellation_reasons: dict[str, int]
