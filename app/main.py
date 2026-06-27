from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seeder import seed_database


app = FastAPI(title="QR System - Hotel Cacique")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-Staff-Token", "ngrok-skip-browser-warning"],
)

app.include_router(router, prefix="/api")


@app.middleware("http")
async def security_headers(request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_request_bytes:
        return JSONResponse(status_code=413, content={"detail": "Solicitud demasiado grande"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def ensure_sqlite_columns() -> None:
    if not str(settings.database_url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        order_columns = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info("order")')}
        if "included_drinks_json" not in order_columns:
            connection.exec_driver_sql('ALTER TABLE "order" ADD COLUMN included_drinks_json TEXT')
        staff_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(staff_user)")}
        if "username" not in staff_columns:
            connection.exec_driver_sql("ALTER TABLE staff_user ADD COLUMN username VARCHAR(60)")
        if "password_hash" not in staff_columns:
            connection.exec_driver_sql("ALTER TABLE staff_user ADD COLUMN password_hash VARCHAR(128)")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
