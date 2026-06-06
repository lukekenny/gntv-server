from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from gntv_server.models import GuestSession, PairingCode
from gntv_server.models.enums import GuestSessionState
from gntv_server.services.pairing import PairingService
from tests.service_fakes import FakeAsyncSession, FakeResult


def make_guest_session(
    *,
    state: GuestSessionState = GuestSessionState.IDLE,
    now: datetime | None = None,
) -> GuestSession:
    current_time = now or datetime.now(UTC)
    return GuestSession(
        id=uuid4(),
        property_id=uuid4(),
        room_id=uuid4(),
        tv_device_id=uuid4(),
        state=state,
        qr_token_hash=PairingService.hash_token("initial-token"),
        expires_at=current_time + timedelta(minutes=10),
        release_after_at=current_time + timedelta(hours=1),
    )


def test_pin_generation_and_validation() -> None:
    pin = PairingService.generate_pin()
    pin_hash = PairingService.hash_pin(pin)

    assert len(pin) == 4
    assert pin.isdigit()
    assert pin not in pin_hash
    assert PairingService.verify_pin(pin, pin_hash)
    assert not PairingService.verify_pin("9999" if pin != "9999" else "0000", pin_hash)


def test_token_hashing_and_validation() -> None:
    token = PairingService.generate_qr_token()
    token_hash = PairingService.hash_token(token)

    assert token != token_hash
    assert PairingService.verify_token(token, token_hash)
    assert not PairingService.verify_token("different-token", token_hash)


def test_pairing_code_expiry_and_consumption() -> None:
    now = datetime.now(UTC)
    pin = "1234"
    pairing_code = PairingCode(
        id=uuid4(),
        tv_device_id=uuid4(),
        code_hash=PairingService.hash_pin(pin),
        expires_at=now - timedelta(seconds=1),
    )

    assert not PairingService.pairing_code_is_valid(pairing_code, pin, now=now)

    pairing_code.expires_at = now + timedelta(minutes=1)
    pairing_code.consumed_at = now
    assert not PairingService.pairing_code_is_valid(pairing_code, pin, now=now)


@pytest.mark.anyio
async def test_create_or_rotate_stores_only_hashes() -> None:
    now = datetime.now(UTC)
    guest_session = make_guest_session(now=now)
    session = FakeAsyncSession([FakeResult()])
    service = PairingService(session)  # type: ignore[arg-type]

    credentials = await service.create_or_rotate_pairing_code(
        tv_device_id=guest_session.tv_device_id,
        guest_session=guest_session,
        now=now,
    )

    assert credentials.pin != credentials.pairing_code.code_hash
    assert credentials.pairing_code.display_code_last4 is None
    assert guest_session.qr_token_hash == service.hash_token(credentials.qr_token)
    assert credentials.qr_token != guest_session.qr_token_hash
    assert guest_session.state == GuestSessionState.PIN_DISPLAYED


@pytest.mark.anyio
async def test_expire_pairing_codes_updates_active_codes() -> None:
    now = datetime.now(UTC)
    pairing_code = PairingCode(
        id=uuid4(),
        tv_device_id=uuid4(),
        code_hash=PairingService.hash_pin("1234"),
        expires_at=now + timedelta(minutes=5),
    )
    session = FakeAsyncSession([FakeResult(scalar_values=[pairing_code])])
    service = PairingService(session)  # type: ignore[arg-type]

    count = await service.expire_pairing_codes(
        tv_device_id=pairing_code.tv_device_id,
        now=now,
    )

    assert count == 1
    assert pairing_code.expires_at == now


@pytest.mark.anyio
async def test_validate_qr_token_and_pin_consumes_code() -> None:
    now = datetime.now(UTC)
    qr_token = "opaque-qr-token"
    pin = "1234"
    guest_session = make_guest_session(
        state=GuestSessionState.PIN_DISPLAYED,
        now=now,
    )
    guest_session.qr_token_hash = PairingService.hash_token(qr_token)
    pairing_code = PairingCode(
        id=uuid4(),
        tv_device_id=guest_session.tv_device_id,
        code_hash=PairingService.hash_pin(pin),
        expires_at=now + timedelta(minutes=5),
    )
    guest_session.pairing_code_id = pairing_code.id
    session = FakeAsyncSession([FakeResult(row=(guest_session, pairing_code))])
    service = PairingService(session)  # type: ignore[arg-type]

    validated = await service.validate_qr_token_and_pin(
        qr_token=qr_token,
        pin=pin,
        now=now,
    )

    assert validated.guest_session is guest_session
    assert validated.pairing_code is pairing_code
    assert pairing_code.consumed_at == now
    assert guest_session.state == GuestSessionState.PAIRING_PENDING
