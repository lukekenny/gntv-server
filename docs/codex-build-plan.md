# Codex Build Plan

This document is intended to be handed to Codex as a staged implementation plan for building `gntv-server` from scratch.

## Global instruction for Codex

Build this project incrementally. Each task should leave the repository in a working state with tests passing. Do not skip migrations, tests, or Docker wiring. Follow `AGENTS.md`, `docs/schema.md`, and `docs/api-contract.md`.

Use raw UniFi HTTP integration initially. Do not use a third-party UniFi package unless explicitly requested.

Critical rule: guest session release/unassign must clear UniFi network override, not restore a previous override.

## Task 1 — Project scaffold

Create the basic Python service structure.

Expected output:

```text
gntv_server/
  __init__.py
  main.py
  core/
  db/
  models/
  schemas/
  api/
  services/
  integrations/
  templates/
  static/
tests/
alembic/
pyproject.toml
Dockerfile
docker-compose.yml
.env.example
README.md
```

Requirements:

- FastAPI application with `/healthz` endpoint.
- Pydantic settings loaded from environment.
- PostgreSQL DSN from `DATABASE_URL`.
- ruff and pytest configured.
- Docker Compose starts app and Postgres.

Acceptance checks:

```bash
pytest
ruff check .
docker compose up --build
```

## Task 2 — Database foundation and migrations

Implement SQLAlchemy models and Alembic migrations for the schema in `docs/schema.md`.

Start with these tables:

- `properties`
- `unifi_controllers`
- `networks`
- `rooms`
- `tv_devices`
- `branding_profiles`
- `pairing_codes`
- `guest_clients`
- `guest_sessions`
- `network_overrides`
- `jobs`
- `audit_events`
- `usage_events`

Requirements:

- UUID primary keys.
- Timezone-aware timestamps.
- Proper foreign keys and indexes.
- Enum handling that is migration-friendly.
- Repository/session helper for DB access.

Acceptance checks:

```bash
alembic upgrade head
pytest
```

## Task 3 — UniFi integration client

Create `gntv_server/integrations/unifi.py`.

Implement:

- `list_networks()`
- `list_users()`
- `get_user(user_id)`
- `apply_network_override(user_id, network_id, site_id)`
- `clear_network_override(user_id, site_id)`
- `find_user_by_ip(ip_address)`

Requirements:

- Use `httpx`.
- Support `X-API-Key` auth.
- Support configurable TLS verification.
- Raise typed exceptions for auth, connectivity, not found, and unexpected response errors.
- Unit tests must mock HTTP responses.

Clear override payload must be:

```json
{
  "virtual_network_override_enabled": false,
  "virtual_network_override_id": "",
  "site_id": "<site-id>"
}
```

## Task 4 — Core service layer

Create services that encapsulate business logic:

- `RoomService`
- `TVDeviceService`
- `PairingService`
- `GuestSessionService`
- `NetworkOverrideService`
- `AuditService`

Requirements:

- Route handlers should be thin.
- Services should be independently testable.
- State transitions should be explicit.
- Applying an override creates a `network_overrides` row and an audit event.
- Releasing a guest session clears the UniFi override and creates an audit event.
- Release must be idempotent.

## Task 5 — Admin API, JSON first

Implement the admin API from `docs/api-contract.md` as JSON endpoints first, before building polished HTML pages.

Minimum endpoints:

- `GET /api/admin/properties`
- `POST /api/admin/properties`
- `GET /api/admin/unifi/controllers`
- `POST /api/admin/unifi/controllers`
- `POST /api/admin/unifi/controllers/{id}/test`
- `POST /api/admin/unifi/controllers/{id}/sync-networks`
- `GET /api/admin/rooms`
- `POST /api/admin/rooms`
- `GET /api/admin/tv-devices`
- `GET /api/admin/tv-devices/{id}`
- `GET /api/admin/audit-events`

For the first implementation, protect admin endpoints with a simple admin bearer token from environment, e.g. `ADMIN_TOKEN`. This can be replaced later with session auth.

## Task 6 — TV API

Implement:

- `POST /api/tv/register`
- `GET /api/tv/config`
- `POST /api/tv/heartbeat`
- optional stub for `POST /api/tv/cast-state`

Requirements:

- TV devices authenticate with bearer token.
- `/api/tv/config` returns branding, room, QR URL, PIN, expiry, and screen mode.
- Generate short-lived QR tokens and 4-digit PINs.
- Store only token/PIN hashes in the database unless a deliberate exception is documented for display/debugging.
- TV heartbeat should update `last_heartbeat_at`, `last_ip`, `app_version`, and current screen mode if stored.

## Task 7 — Guest portal and pairing flow

Implement:

- `GET /join?t={qr_token}`
- `POST /api/guest/pair`
- optional `POST /api/guest/release`

Requirements:

- Render a basic mobile-friendly PIN form for `/join`.
- Validate QR token expiry and PIN.
- Determine guest IP from request. Be careful with proxy headers; only trust them when configured.
- Find the UniFi client by `last_ip`.
- Apply room VLAN override.
- Move TV state to `casting_instructions` for five minutes.
- Return a clear success/failure page or JSON response.
- Rate-limit PIN attempts by IP and token. A simple DB-backed limiter is acceptable initially.

## Task 8 — Background worker

Implement a simple DB-backed worker loop.

Jobs to support:

- `sync_unifi_networks`
- `adb_enroll_tv_device`
- `apply_network_override`
- `release_network_override`
- `expire_guest_sessions`
- `health_check_tv_devices`
- `reconcile_unifi_state`

Requirements:

- Jobs can be run in a separate Docker service: `worker`.
- Jobs have attempts, backoff, `run_after`, `locked_at`, and `locked_by`.
- Expired guest sessions must clear guest network overrides.
- Worker must be safe to restart.

## Task 9 — ADB enrollment

Implement ADB operations as a service, initially shelling out to the `adb` binary available in the container.

Functions:

- `adb_connect(host, port)`
- `adb_install(serial, apk_path)`
- `adb_shell(serial, args)`
- `adb_provision_app(serial, provisioning_token, server_url)`
- optional launcher setup commands after manual confirmation

Admin endpoint:

- `POST /api/admin/tv-devices/enroll`

Requirements:

- ADB operations must run as background jobs.
- Capture stdout/stderr for job logs, but avoid logging secrets.
- Enrollment should create a `tv_devices` row in `enrolling` state.
- After installing/provisioning the app, find the TV in UniFi by IP/MAC and optionally apply the room network override.

## Task 10 — Admin web management page

Add simple server-rendered admin pages.

Pages:

- Dashboard / stats summary
- UniFi settings
- Rooms
- TV devices
- Enroll TV device form
- Current clients/sessions by room
- Audit log

The UI can be plain HTML with Jinja2 initially. HTMX may be used if helpful, but avoid a complex frontend build step until needed.

## Task 11 — Usage statistics

Record `usage_events` for:

- QR generated/shown
- PIN attempt
- PIN success
- PIN failure
- guest override applied
- guest session released
- guest session expired
- UniFi API failure

Expose:

- `GET /api/admin/stats/summary`

## Task 12 — Hardening and deployment polish

Add:

- `.env.example`
- production Dockerfile
- Docker Compose with app, worker, and Postgres
- structured logging
- request IDs
- backup/restore notes
- clear README setup instructions
- test fixtures for fake UniFi responses

Security hardening:

- never log UniFi API keys
- rate-limit guest pairing
- short QR/PIN expiry
- admin auth on every admin endpoint
- CSRF protection if using cookie sessions later

## Suggested first milestone

The first useful milestone is not the full admin UI. It is:

1. Docker app + Postgres boots.
2. Admin can configure UniFi controller and sync networks.
3. Admin can create a room mapped to a UniFi network.
4. A fake TV can call `/api/tv/config` and receive QR/PIN.
5. Guest can submit QR/PIN.
6. Backend finds guest by IP in mocked UniFi data and applies override.
7. Session expiry clears override.

Build that first, then add ADB enrollment and management UI polish.
