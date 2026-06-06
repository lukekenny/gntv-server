# Draft Database Schema

This document defines the first-pass relational model for `gntv-server`. It is intentionally implementation-oriented but not yet a migration file.

## Design principles

- Treat rooms, TV devices, guest devices, and casting sessions as distinct entities.
- Persist UniFi identifiers exactly as returned by UniFi, especially network `_id` values and client/user `_id` values.
- Make all network override actions auditable and reversible.
- Keep the Google TV app generic; room-specific data should come from the backend.
- Prefer explicit state transitions over ad hoc booleans.

## Core enums

### `tv_device_status`

- `enrolling`
- `provisioned`
- `online`
- `offline`
- `disabled`
- `error`

### `guest_session_state`

- `idle`
- `pin_displayed`
- `pairing_pending`
- `paired`
- `casting_instructions`
- `casting_active`
- `timeout_pending`
- `released`
- `expired`
- `error`

### `override_state`

- `pending`
- `applied`
- `release_pending`
- `released`
- `failed`

### `job_state`

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

## Tables

## `properties`

Represents a deployment site, building, or accommodation property.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk | Internal identifier |
| `name` | text | Display/admin name |
| `slug` | text unique | URL/admin-safe identifier |
| `timezone` | text | e.g. `Australia/Melbourne` |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

## `unifi_controllers`

UniFi API configuration. Secrets should be encrypted at rest if stored in DB; alternatively store API key only in environment variables.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk | `properties.id` |
| `name` | text | e.g. `Main UDM` |
| `base_url` | text | e.g. `https://172.16.0.1/proxy/network` |
| `site` | text | e.g. `default` |
| `api_key_ref` | text | Reference to env/secret manager, not necessarily raw key |
| `verify_tls` | boolean | Default false for local self-signed UniFi certs |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

## `networks`

Cached UniFi network/VLAN records from `/api/s/{site}/rest/networkconf`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk | Internal identifier |
| `property_id` | uuid fk |  |
| `unifi_controller_id` | uuid fk |  |
| `unifi_network_id` | text | UniFi `_id`, e.g. `683b4c...` |
| `name` | text | UniFi network name |
| `vlan` | integer nullable | VLAN number where applicable |
| `ip_subnet` | cidr nullable | e.g. `172.16.50.1/24` |
| `mdns_enabled` | boolean nullable | Cached from UniFi |
| `network_isolation_enabled` | boolean nullable | Cached from UniFi |
| `raw` | jsonb | Full UniFi payload for diagnostics |
| `last_synced_at` | timestamptz |  |

Unique key: `(unifi_controller_id, unifi_network_id)`.

## `rooms`

Represents a guest room or casting zone.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk |  |
| `room_code` | text | Human/admin code, e.g. `101` |
| `display_name` | text | e.g. `Room 101` |
| `network_id` | uuid fk | Target room VLAN/network |
| `enabled` | boolean |  |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

Unique key: `(property_id, room_code)`.

## `tv_devices`

Google TV / Android TV devices running the companion app.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk | Device identifier used by TV app |
| `room_id` | uuid fk | Assigned room |
| `name` | text | Admin label |
| `adb_serial` | text nullable | e.g. `192.168.1.50:5555` |
| `last_ip` | inet nullable | Last observed IP |
| `mac` | macaddr nullable | Device MAC if known |
| `unifi_user_id` | text nullable | UniFi client/user `_id` |
| `unifi_network_override_id` | text nullable | Room network `_id` applied to TV |
| `status` | tv_device_status |  |
| `app_version` | text nullable | From heartbeat |
| `provisioning_token_hash` | text | Used by TV app auth |
| `last_heartbeat_at` | timestamptz nullable |  |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

## `branding_profiles`

Display configuration consumed by the TV app.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk |  |
| `name` | text |  |
| `logo_url` | text nullable |  |
| `background_url` | text nullable |  |
| `instruction_title` | text |  |
| `instruction_text` | text | Markdown or plain text; choose one in implementation |
| `cast_instruction_title` | text | Second-screen title |
| `cast_instruction_text` | text | How-to-cast instructions after pairing |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

A room may later override this via a `room_branding_profile_id` column if needed.

## `pairing_codes`

Short-lived PINs shown on TV.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `tv_device_id` | uuid fk |  |
| `code_hash` | text | Store hash, not raw 4-digit PIN |
| `display_code_last4` | text nullable | Optional debug/display cache if acceptable |
| `expires_at` | timestamptz |  |
| `consumed_at` | timestamptz nullable |  |
| `created_at` | timestamptz |  |

Index: `expires_at`. Consider rate limiting by IP, not only by code.

## `guest_clients`

Represents a guest phone/tablet/laptop observed during onboarding.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk |  |
| `unifi_controller_id` | uuid fk |  |
| `unifi_user_id` | text nullable | UniFi `/rest/user/{id}` |
| `mac` | macaddr nullable | May not be available from HTTP request alone |
| `last_ip` | inet | IP seen by portal or UniFi |
| `hostname` | text nullable | From UniFi |
| `user_agent` | text nullable | From portal |
| `first_seen_at` | timestamptz |  |
| `last_seen_at` | timestamptz |  |

Unique index where possible: `(unifi_controller_id, mac)`.

## `guest_sessions`

A pairing/casting lifecycle between a guest client and a room TV.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk |  |
| `room_id` | uuid fk |  |
| `tv_device_id` | uuid fk |  |
| `guest_client_id` | uuid fk nullable | Set after client identified |
| `pairing_code_id` | uuid fk nullable |  |
| `state` | guest_session_state |  |
| `qr_token_hash` | text | Token embedded in QR URL |
| `paired_at` | timestamptz nullable |  |
| `cast_started_at` | timestamptz nullable | Future signal, if detectable |
| `cast_ended_at` | timestamptz nullable | Future signal, if detectable |
| `expires_at` | timestamptz | Guest pairing timeout |
| `release_after_at` | timestamptz | Cleanup deadline |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

## `network_overrides`

Every UniFi virtual network override applied by the system.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `guest_session_id` | uuid fk nullable | Nullable for TV provisioning overrides |
| `tv_device_id` | uuid fk nullable |  |
| `guest_client_id` | uuid fk nullable |  |
| `unifi_controller_id` | uuid fk |  |
| `unifi_user_id` | text | Target `/rest/user/{id}` |
| `from_network_id` | uuid fk nullable | Best-effort cached previous network |
| `to_network_id` | uuid fk nullable | Internal network id |
| `to_unifi_network_id` | text | UniFi network `_id` |
| `previous_override_enabled` | boolean nullable | Captured before apply |
| `previous_override_id` | text nullable | Captured before apply |
| `state` | override_state |  |
| `applied_at` | timestamptz nullable |  |
| `released_at` | timestamptz nullable |  |
| `last_error` | text nullable |  |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

Release should normally restore the previous override state, not blindly clear it, unless policy says otherwise.

## `jobs`

Background work queue if not using Celery/RQ. This keeps Docker deployment simple.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `type` | text | e.g. `adb_enroll`, `apply_override`, `release_session` |
| `state` | job_state |  |
| `payload` | jsonb |  |
| `attempts` | integer |  |
| `run_after` | timestamptz |  |
| `locked_at` | timestamptz nullable |  |
| `locked_by` | text nullable | Worker id |
| `last_error` | text nullable |  |
| `created_at` | timestamptz |  |
| `updated_at` | timestamptz |  |

## `audit_events`

Immutable operational log.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk nullable |  |
| `actor_type` | text | `admin`, `system`, `tv_device`, `guest` |
| `actor_id` | text nullable |  |
| `event_type` | text | e.g. `guest.paired`, `unifi.override.applied` |
| `entity_type` | text nullable |  |
| `entity_id` | uuid nullable |  |
| `ip_address` | inet nullable |  |
| `metadata` | jsonb |  |
| `created_at` | timestamptz |  |

## `usage_events`

Aggregated/statistical event stream.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid pk |  |
| `property_id` | uuid fk |  |
| `room_id` | uuid fk nullable |  |
| `tv_device_id` | uuid fk nullable |  |
| `guest_session_id` | uuid fk nullable |  |
| `event_type` | text | e.g. `qr_shown`, `pin_success`, `session_released` |
| `occurred_at` | timestamptz |  |
| `metadata` | jsonb |  |

## Notes and open questions

1. Detecting “casting ended” may be difficult unless the TV app can observe app foreground/background state or another signal. Initial cleanup should rely on timeout plus manual/admin release.
2. Guest MAC discovery from a web request is not possible directly across normal L3 routing. The backend should map request IP to UniFi `/rest/user` data, then extract MAC/client `_id` from UniFi.
3. PINs should be short-lived and rate-limited. A 4-digit PIN is usable only because the QR token and TV/session context also constrain the attack surface.
4. For safety, release should restore a client’s previous override state where possible, rather than always setting `virtual_network_override_enabled=false`.
