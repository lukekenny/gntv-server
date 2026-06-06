# gntv-server

Backend server for Guest Network TV (`gntv`) room onboarding.

This service coordinates Google TV / Android TV welcome screens, guest PIN onboarding, UniFi virtual network overrides, and session lifecycle management for room-specific casting.

The companion Android / Google TV application will live in `gntv-tv`.

## Documentation

- [Database schema](docs/schema.md)
- [API contract](docs/api-contract.md)
- [Codex build plan](docs/codex-build-plan.md)
- [Repository agent instructions](AGENTS.md)

## Local development

This project targets Python 3.12+ with FastAPI, PostgreSQL, pytest, ruff,
and Docker Compose.

Create a local environment file:

```bash
cp .env.example .env
```

Update `.env` for your local UniFi controller and admin token. The checked-in
example uses development placeholders only.

Install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the quality checks:

```bash
ruff check .
ruff format --check .
pytest
```

Start PostgreSQL and run database migrations against the database configured by
`DATABASE_URL`:

```bash
docker compose up -d postgres
alembic upgrade head
```

Start the app and PostgreSQL with Docker Compose:

```bash
docker compose up --build
```

Migrations can also run inside the application image:

```bash
docker compose run --rm app alembic upgrade head
```

Open the health check endpoint:

```text
http://localhost:8000/healthz
```

Admin JSON endpoints are available under `/api/admin` and require the token
configured by `ADMIN_TOKEN`:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  http://localhost:8000/api/admin/properties
```

UniFi controller records store an environment-variable reference such as
`UNIFI_API_KEY`, not the API key itself.

The companion TV app registers through `/api/tv/register` with its one-time
provisioning token. Subsequent `/api/tv/config`, `/api/tv/heartbeat`, and
`/api/tv/cast-state` requests use the permanent bearer token returned once by
registration.

## Initial architectural assumptions

- Python backend, likely FastAPI.
- Docker deployment.
- PostgreSQL database, configured via `DATABASE_URL` / `postgres://...`.
- UniFi Network API configured via environment or admin settings.
- Google TV devices are provisioned by ADB and then assigned to room VLANs using UniFi virtual network override.
- Guest devices are temporarily moved into the room VLAN after successful PIN entry.
- When a guest session is released, expired, or manually unassigned, the guest client's UniFi network override must be cleared by setting `virtual_network_override_enabled=false`. Do not restore a previous guest override.
