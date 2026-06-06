# Agent Instructions for gntv-server

These instructions are for Codex or any automated coding agent working in this repository.

## Project intent

`gntv-server` is a Python/Docker/PostgreSQL backend for hospitality-style Google TV guest casting. It manages rooms, Google TV devices, guest pairing sessions, UniFi client lookup, and UniFi Virtual Network Override operations.

The companion Android TV app is expected to live in a separate repository named `gntv-tv`.

## Preferred stack

Use this stack unless explicitly instructed otherwise:

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x ORM
- Alembic migrations
- PostgreSQL
- Pydantic v2 / pydantic-settings
- httpx for UniFi HTTP calls
- Jinja2 templates for the guest/admin HTML pages unless a frontend framework is later chosen
- pytest for tests
- ruff for linting/formatting
- Docker and Docker Compose

A DB-backed job table/worker is preferred initially over Celery/Redis, to keep deployment simple. Redis/Celery can be added later if operationally necessary.

## Critical network override policy

Guest release/unassign behaviour is intentionally simple:

- When pairing a guest client, apply UniFi virtual network override to the room network.
- When releasing, expiring, or manually unassigning a guest client, always clear the guest client's override:
  - `virtual_network_override_enabled: false`
  - `virtual_network_override_id: ""`
- Do not restore a previous guest override.

Reason: if a guest pairs with one room and later pairs with a different room, releasing the second session must not move them back to the first room's VLAN.

It is acceptable to record previous override fields for audit/debugging, but release logic for guest clients must clear the override.

TV-device provisioning is separate. A TV device may have a persistent room VLAN override applied during enrollment.

## UniFi API contract

Use raw HTTP endpoints first; do not introduce a third-party UniFi wrapper unless there is a clear benefit.

Expected base URL example:

```text
https://172.16.0.1/proxy/network
```

Headers:

```http
X-API-Key: <key>
Accept: application/json
Content-Type: application/json
```

Important endpoints:

```http
GET /api/s/{site}/rest/networkconf
GET /api/s/{site}/rest/user
GET /api/s/{site}/rest/user/{user_id}
PUT /api/s/{site}/rest/user/{user_id}
```

Apply override:

```json
{
  "virtual_network_override_enabled": true,
  "virtual_network_override_id": "<unifi-network-id>",
  "site_id": "<site-id>"
}
```

Clear guest override:

```json
{
  "virtual_network_override_enabled": false,
  "virtual_network_override_id": "",
  "site_id": "<site-id>"
}
```

## Coding principles

- Keep UniFi-specific code isolated in an integration/client module.
- Keep business logic in service classes/functions, not directly in FastAPI route handlers.
- Make session state transitions explicit and testable.
- Every UniFi override apply/clear must create an audit event.
- Avoid storing raw secrets in logs, audit metadata, or test fixtures.
- Use idempotent operations where possible; retries should not create duplicate active sessions or duplicate overrides.
- Prefer deterministic tests using mocked UniFi responses.

## Minimum quality gate

Before declaring a task complete, run or add the appropriate equivalent of:

```bash
ruff check .
ruff format --check .
pytest
```

If Docker files exist, also verify that the app starts with Docker Compose.
