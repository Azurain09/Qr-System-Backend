# QR System - Backend

FastAPI service for a hotel breakfast ordering system. It supports QR-driven orders, authenticated staff workflows, real-time operational updates, reports, and Excel exports.

## Highlights

- REST API built with FastAPI.
- SQLite persistence through SQLAlchemy.
- Staff authentication with time-limited signed tokens.
- Role-aware authorization for kitchen, reception, and management.
- WebSocket notifications for order and catalog updates.
- Daily reports and Excel exports.
- Basic security headers, CORS configuration, and request size limits.

## Stack

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- Uvicorn

## Local setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Replace the placeholder values in .env before starting the service.
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive API documentation is available at `/docs` for local development.

## Required environment variables for deployment

| Variable | Purpose |
| --- | --- |
| `STAFF_PASSWORD` | Unique staff password for the deployed environment. |
| `STAFF_TOKEN_SECRET` | Long random value used to sign staff tokens. |
| `ALLOWED_ORIGINS` | Comma-separated list of approved frontend origins. |
| `FORCE_OPEN_24H` | Set to `true` only in a controlled demo environment. |

Generate a deployment secret locally with:

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

## Security notes

- Never commit a real `.env`, database file, token, password, or personally identifiable guest data.
- Use synthetic records for screenshots, demos, and portfolio presentations.
- Rotate any credential that was ever committed, even if it has since been removed.
- Keep production credentials only in the deployment provider's encrypted environment-variable settings.

## Portfolio context

This repository demonstrates backend API design, authorization, real-time communications, reporting, and practical deployment-oriented configuration.
