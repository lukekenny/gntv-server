# Draft API Contract

This is the first-pass API contract for `gntv-server`. The likely implementation is Python/FastAPI, returning JSON unless otherwise noted.

## Authentication model

Three actor classes are expected:

1. **Admin web UI** — cookie/session or bearer token auth.
2. **Google TV app** — device token auth, preferably provisioned during ADB enrollment.
3. **Guest portal** — anonymous, constrained by QR token, PIN, rate limits, and expiry.

Suggested headers:

```http
Authorization: Bearer <token>
Accept: application/json
Content-Type: application/json
```

## Common response shapes

### Success

```json
{
  "data": {},
  "meta": {}
}
```

### Error

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable message",
    "details": {}
  }
}
```

## Admin API

Base path: `/api/admin`

## Properties

### `GET /api/admin/properties`

List properties visible to the current admin.

### `POST /api/admin/properties`

Create a property.

```json
{
  "name": "Small Creek",
  "slug": "small-creek",
  "timezone": "Australia/Melbourne"
}
```

## UniFi settings

### `GET /api/admin/unifi/controllers`

List configured UniFi controllers.

### `POST /api/admin/unifi/controllers`

Create/update UniFi controller settings.

```json
{
  "property_id": "uuid",
  "name": "Main UDM",
  "base_url": "https://172.16.0.1/proxy/network",
  "site": "default",
  "api_key": "secret",
  "verify_tls": false
}
```

Implementation note: if API keys are kept in env vars, accept `api_key_ref` instead of raw `api_key`.

### `POST /api/admin/unifi/controllers/{controller_id}/test`

Tests UniFi connectivity and permissions.

Expected checks:

- `GET /api/s/{site}/rest/networkconf`
- `GET /api/s/{site}/rest/user`

### `POST /api/admin/unifi/controllers/{controller_id}/sync-networks`

Fetches UniFi networks and updates the local `networks` cache.

## Rooms

### `GET /api/admin/rooms`

Query params:

- `property_id`
- `enabled`

### `POST /api/admin/rooms`

```json
{
  "property_id": "uuid",
  "room_code": "101",
  "display_name": "Room 101",
  "network_id": "uuid",
  "enabled": true
}
```

### `PUT /api/admin/rooms/{room_id}`

Update room metadata or target network.

### `DELETE /api/admin/rooms/{room_id}`

Soft-disable preferred. Hard delete should be blocked if audit/session history exists.

## TV device enrollment

### `POST /api/admin/tv-devices/enroll`

Begins ADB enrollment and assigns the TV to its room VLAN via UniFi network override.

```json
{
  "room_id": "uuid",
  "name": "Room 101 Google TV Streamer",
  "adb_host": "172.16.1.126",
  "adb_port": 5555,
  "install_apk": true,
  "set_launcher": true,
  "apply_room_network_override": true
}
```

Response:

```json
{
  "data": {
    "job_id": "uuid",
    "tv_device_id": "uuid",
    "status": "enrolling"
  }
}
```

Expected job steps:

1. `adb connect <host>:<port>`
2. Install/update `gntv-tv.apk`
3. Generate/provision device token
4. Optionally configure launcher/default home behaviour
5. Locate TV client in UniFi by IP/MAC
6. Apply virtual network override to room network
7. Mark device `provisioned`

### `GET /api/admin/tv-devices`

List devices and status.

### `GET /api/admin/tv-devices/{tv_device_id}`

Device detail including room, heartbeat, current session, and UniFi identifiers.

### `DELETE /api/admin/tv-devices/{tv_device_id}`

Remove/disable a TV device. Optional flags:

```json
{
  "uninstall_apk": false,
  "clear_network_override": true
}
```

### `POST /api/admin/tv-devices/{tv_device_id}/reconcile`

Compare local state with UniFi state and optionally repair drift.

## Guest/session management

### `GET /api/admin/rooms/{room_id}/sessions/current`

Returns current guest session for a room, if any.

### `GET /api/admin/tv-devices/{tv_device_id}/clients`

Shows clients currently assigned to a TV/room by active sessions and UniFi overrides.

### `POST /api/admin/sessions/{session_id}/release`

Manually release a guest session and undo network override.

```json
{
  "reason": "admin_requested"
}
```

### `POST /api/admin/guest-clients/{guest_client_id}/unassign`

Remove or restore a guest client’s UniFi override.

```json
{
  "mode": "restore_previous"
}
```

Allowed `mode` values:

- `restore_previous`
- `clear_override`

## Usage/stats

### `GET /api/admin/stats/summary`

Query params:

- `property_id`
- `from`
- `to`

Response includes:

- QR displays
- PIN attempts
- successful pairings
- failed pairings
- sessions released
- sessions expired
- average session duration
- UniFi API error count

### `GET /api/admin/audit-events`

Paginated audit log.

## TV app API

Base path: `/api/tv`

All TV endpoints require a device token.

## `POST /api/tv/register`

Used during enrollment to bind the installed app to a backend `tv_device_id`. This may be called by an ADB provisioning command or by the app on first launch with a one-time token.

```json
{
  "provisioning_token": "one-time-token",
  "device_info": {
    "android_id": "...",
    "model": "Google TV Streamer",
    "app_version": "0.1.0"
  }
}
```

## `GET /api/tv/config`

Returns the welcome-screen payload for the authenticated TV device.

Response:

```json
{
  "data": {
    "tv_device_id": "uuid",
    "room": {
      "id": "uuid",
      "display_name": "Room 101"
    },
    "branding": {
      "logo_url": "https://example.test/assets/logo.png",
      "background_url": "https://example.test/assets/background.jpg",
      "instruction_title": "Cast to your room TV",
      "instruction_text": "Connect to guest Wi-Fi, scan the QR code, enter the PIN, then choose this TV from your cast menu.",
      "cast_instruction_title": "You are connected",
      "cast_instruction_text": "Open YouTube, Netflix, Spotify or another Cast-enabled app and tap the Cast icon."
    },
    "pairing": {
      "pin": "1234",
      "qr_url": "https://guest.example.com/join?t=opaque-token",
      "expires_at": "2026-06-06T10:15:00Z"
    },
    "screen": {
      "mode": "welcome"
    },
    "poll_after_seconds": 5
  }
}
```

The backend should rotate PINs and QR tokens periodically.

## `POST /api/tv/heartbeat`

```json
{
  "app_version": "0.1.0",
  "foreground": true,
  "screen_mode": "welcome",
  "local_ip": "172.16.50.252"
}
```

Response may instruct the TV to change screen mode:

```json
{
  "data": {
    "desired_screen_mode": "casting_instructions",
    "poll_after_seconds": 5
  }
}
```

Allowed screen modes:

- `welcome`
- `pairing_pending`
- `casting_instructions`
- `maintenance`
- `error`

## `POST /api/tv/cast-state`

Optional future endpoint if the Android app can detect cast lifecycle signals.

```json
{
  "state": "started",
  "session_hint": "opaque-or-null"
}
```

Allowed states:

- `started`
- `ended`
- `unknown`

## Guest portal API

Base path: `/api/guest`

## `GET /join?t={qr_token}`

Human-facing QR target page. Renders a simple page with PIN entry form.

The server should validate:

- QR token exists
- token is not expired
- TV device is enabled
- room is enabled

## `POST /api/guest/pair`

Submit PIN from QR page.

```json
{
  "qr_token": "opaque-token",
  "pin": "1234"
}
```

Server-side behaviour:

1. Validate QR token and PIN.
2. Determine apparent guest IP from request.
3. Query UniFi users/clients and find matching `last_ip`.
4. Persist or update `guest_clients` record.
5. Apply UniFi virtual network override to room network:

```json
{
  "virtual_network_override_enabled": true,
  "virtual_network_override_id": "<room-unifi-network-id>",
  "site_id": "<unifi-site-id>"
}
```

6. Transition session to `paired` / `casting_instructions`.
7. TV will show second-screen instructions on next poll/heartbeat.

Response:

```json
{
  "data": {
    "status": "paired",
    "room_display_name": "Room 101",
    "message": "You are connected. Open a Cast-enabled app and select the room TV.",
    "expires_at": "2026-06-06T11:15:00Z"
  }
}
```

### `POST /api/guest/release`

Optional guest-facing disconnect button.

```json
{
  "session_token": "opaque-session-token"
}
```

## UniFi integration contract

Initial raw endpoints observed/tested:

### List networks

```http
GET {UNIFI_BASE_URL}/api/s/{site}/rest/networkconf
X-API-Key: <key>
Accept: application/json
```

Use returned network `_id` as `virtual_network_override_id`.

### List users/clients

```http
GET {UNIFI_BASE_URL}/api/s/{site}/rest/user
X-API-Key: <key>
Accept: application/json
```

Match guest client by `last_ip` where possible, then retain:

- `_id`
- `mac`
- `hostname`
- `last_connection_network_id`
- `virtual_network_override_enabled`
- `virtual_network_override_id`

### Get user/client

```http
GET {UNIFI_BASE_URL}/api/s/{site}/rest/user/{user_id}
X-API-Key: <key>
Accept: application/json
```

### Apply virtual network override

```http
PUT {UNIFI_BASE_URL}/api/s/{site}/rest/user/{user_id}
X-API-Key: <key>
Accept: application/json
Content-Type: application/json

{
  "virtual_network_override_enabled": true,
  "virtual_network_override_id": "<unifi-network-id>",
  "site_id": "<site-id>"
}
```

### Clear virtual network override

To be verified against UniFi behaviour, likely:

```json
{
  "virtual_network_override_enabled": false,
  "virtual_network_override_id": "",
  "site_id": "<site-id>"
}
```

Preferred release behaviour is to restore the captured previous values from `network_overrides`.

## Background jobs

Minimum jobs:

- `adb_enroll_tv_device`
- `sync_unifi_networks`
- `sync_unifi_clients`
- `apply_network_override`
- `release_network_override`
- `expire_guest_sessions`
- `health_check_tv_devices`
- `reconcile_unifi_state`

## Security and abuse controls

- Rate-limit PIN attempts by IP, QR token, and room.
- Use short-lived QR tokens and PINs.
- Hash PINs and QR/session tokens in the DB.
- Avoid storing raw UniFi API key unless encrypted.
- Maintain audit records for every override apply/release.
- Require admin authentication for all management pages.
- Protect admin mutations with CSRF if cookie-based auth is used.

## Open questions

1. Whether cast start/end can be detected reliably on Google TV without privileged APIs.
2. Whether the TV app should poll `/config` or use a narrower `/state` endpoint after initial load.
3. Whether each TV should have a permanent device token or a rotatable token pair.
4. Whether guest cleanup should be purely timeout-based initially.
