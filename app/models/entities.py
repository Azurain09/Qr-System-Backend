from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Guest(Base):
    __tablename__ = "guest"

    id: Mapped[int] = mapped_column(primary_key=True)
    document: Mapped[str] = mapped_column(String(9), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    orders: Mapped[list["Order"]] = relationship(back_populates="guest")


class BreakfastType(Base):
    __tablename__ = "breakfast_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(Text)
    has_eggs: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EggPrepType(Base):
    __tablename__ = "egg_prep_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExtraCategory(Base):
    __tablename__ = "extra_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    extras: Mapped[list["Extra"]] = relationship(back_populates="category")


class Extra(Base):
    __tablename__ = "extra"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("extra_category.id"))
    name: Mapped[str] = mapped_column(String(100))
    requires_egg_prep: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[ExtraCategory] = relationship(back_populates="extras")


class Table(Base):
    __tablename__ = "table"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ingredient(Base):
    __tablename__ = "ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StaffUser(Base):
    __tablename__ = "staff_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    dni: Mapped[str] = mapped_column(String(8), unique=True)
    role: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "order"

    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guest.id"))
    delivery_location: Mapped[str] = mapped_column(String(20))
    table_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_number: Mapped[str | None] = mapped_column(String(3), nullable=True)
    claimed_included: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="Borrador")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)

    guest: Mapped[Guest] = relationship(back_populates="orders")
    breakfast_detail: Mapped["OrderDetailBreakfast"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    extra_details: Mapped[list["OrderDetailExtra"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderDetailBreakfast(Base):
    __tablename__ = "order_detail_breakfast"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    breakfast_type_id: Mapped[int] = mapped_column(ForeignKey("breakfast_type.id"))
    egg_prep_type_id: Mapped[int | None] = mapped_column(ForeignKey("egg_prep_type.id"), nullable=True)

    order: Mapped[Order] = relationship(back_populates="breakfast_detail")
    breakfast_type: Mapped[BreakfastType] = relationship()
    egg_prep_type: Mapped[EggPrepType | None] = relationship()


class OrderDetailExtra(Base):
    __tablename__ = "order_detail_extra"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    extra_id: Mapped[int] = mapped_column(ForeignKey("extra.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    egg_prep_type_id: Mapped[int | None] = mapped_column(ForeignKey("egg_prep_type.id"), nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)

    order: Mapped[Order] = relationship(back_populates="extra_details")
    extra: Mapped[Extra] = relationship()
    egg_prep_type: Mapped[EggPrepType | None] = relationship()


class Cancellation(Base):
    __tablename__ = "cancellation"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("order.id"), nullable=True)
    order_extra_id: Mapped[int | None] = mapped_column(ForeignKey("order_detail_extra.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="history")


class Report(Base):
    __tablename__ = "report"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[str] = mapped_column(String(10), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[str] = mapped_column(Text)
