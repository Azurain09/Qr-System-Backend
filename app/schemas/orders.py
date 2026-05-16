from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ExtraSelectionIn(BaseModel):
    extra_id: int
    quantity: int = Field(ge=1, le=20)
    egg_prep_type_id: int | None = None


class OrderCreateIn(BaseModel):
    document: str
    full_name: str
    delivery_location: str
    table_number: int | None = None
    room_number: str | None = None
    claimed_included: bool
    breakfast_type_id: int
    egg_prep_type_id: int | None = None
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
    role: str
    is_active: bool = True


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
    cancellation_reason: str | None


class ReportOut(BaseModel):
    date: str
    total_orders: int
    attended_by_origin: dict[str, int]
    breakfast_types: dict[str, int]
    extras: dict[str, int]
    peak_hours: dict[str, int]
    cancellation_reasons: dict[str, int]
