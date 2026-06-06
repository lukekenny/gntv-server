# gntv-server

Backend server for Guest Network TV (`gntv`) room onboarding.

This service is intended to coordinate Google TV / Android TV welcome screens, guest PIN onboarding, UniFi virtual network overrides, and session lifecycle management for room-specific casting.

The companion Android / Google TV application will live in `gntv-tv`.

## Draft documentation

- [Database schema](docs/schema.md)
- [API contract](docs/api-contract.md)

## Initial architectural assumptions

- Python backend, likely FastAPI.
- Docker deployment.
- PostgreSQL database, configured via `DATABASE_URL` / `postgres://...`.
- UniFi Network API configured via environment or admin settings.
- Google TV devices are provisioned by ADB and then assigned to room VLANs using UniFi virtual network override.
- Guest devices are temporarily moved into the room VLAN after successful PIN entry.
