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

Start the app and PostgreSQL with Docker Compose:

```bash
docker compose up --build
```

Open the health check endpoint:

```text
http://localhost:8000/healthz
```

## Initial architectural assumptions

- Python backend, likely FastAPI.
- Docker deployment.
- PostgreSQL database, configured via `DATABASE_URL` / `postgres://...`.
- UniFi Network API configured via environment or admin settings.
- Google TV devices are provisioned by ADB and then assigned to room VLANs using UniFi virtual network override.
- Guest devices are temporarily moved into the room VLAN after successful PIN entry.
- When a guest session is released, expired, or manually unassigned, the guest client's UniFi network override must be cleared by setting `virtual_network_override_enabled=false`. Do not restore a previous guest override.
