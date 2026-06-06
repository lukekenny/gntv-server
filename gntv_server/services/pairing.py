import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import GuestSession, PairingCode
from gntv_server.models.enums import GuestSessionState
from gntv_server.services.exceptions import PairingValidationError
from gntv_server.services.guest_sessions import GuestSessionService
from gntv_server.services.security import hash_opaque_token, verify_opaque_token

PIN_HASH_ALGORITHM = "sha256"
PIN_HASH_ITERATIONS = 120_000
PAIRING_CODE_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class PairingCredentials:
    pin: str
    qr_token: str
    expires_at: datetime
    pairing_code: PairingCode


@dataclass(frozen=True, slots=True)
class ValidatedPairing:
    guest_session: GuestSession
    pairing_code: PairingCode


class PairingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def generate_pin() -> str:
        return f"{secrets.randbelow(10_000):04d}"

    @staticmethod
    def generate_qr_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(token: str) -> str:
        return hash_opaque_token(token)

    @staticmethod
    def verify_token(token: str, expected_hash: str) -> bool:
        return verify_opaque_token(token, expected_hash)

    @staticmethod
    def hash_pin(pin: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            PIN_HASH_ALGORITHM,
            pin.encode("utf-8"),
            salt,
            PIN_HASH_ITERATIONS,
        )
        return (
            f"pbkdf2_{PIN_HASH_ALGORITHM}${PIN_HASH_ITERATIONS}"
            f"${salt.hex()}${digest.hex()}"
        )

    @staticmethod
    def verify_pin(pin: str, encoded_hash: str) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = encoded_hash.split("$")
            if algorithm != f"pbkdf2_{PIN_HASH_ALGORITHM}":
                return False
            digest = hashlib.pbkdf2_hmac(
                PIN_HASH_ALGORITHM,
                pin.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(digest.hex(), digest_hex)

    @classmethod
    def pairing_code_is_valid(
        cls,
        pairing_code: PairingCode,
        pin: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        check_time = now or datetime.now(UTC)
        return (
            pairing_code.consumed_at is None
            and pairing_code.expires_at > check_time
            and cls.verify_pin(pin, pairing_code.code_hash)
        )

    async def create_or_rotate_pairing_code(
        self,
        *,
        tv_device_id: UUID,
        guest_session: GuestSession,
        ttl: timedelta = PAIRING_CODE_TTL,
        now: datetime | None = None,
    ) -> PairingCredentials:
        issued_at = now or datetime.now(UTC)
        await self.expire_pairing_codes(tv_device_id=tv_device_id, now=issued_at)

        pin = self.generate_pin()
        qr_token = self.generate_qr_token()
        expires_at = issued_at + ttl
        pairing_code = PairingCode(
            tv_device_id=tv_device_id,
            code_hash=self.hash_pin(pin),
            display_code_last4=None,
            expires_at=expires_at,
        )
        self.session.add(pairing_code)
        await self.session.flush()

        guest_session.pairing_code_id = pairing_code.id
        guest_session.qr_token_hash = self.hash_token(qr_token)
        guest_session.expires_at = expires_at
        GuestSessionService.transition_state(
            guest_session,
            GuestSessionState.PIN_DISPLAYED,
            now=issued_at,
        )
        await self.session.flush()

        return PairingCredentials(
            pin=pin,
            qr_token=qr_token,
            expires_at=expires_at,
            pairing_code=pairing_code,
        )

    async def expire_pairing_codes(
        self,
        *,
        tv_device_id: UUID,
        now: datetime | None = None,
    ) -> int:
        expiry_time = now or datetime.now(UTC)
        result = await self.session.execute(
            select(PairingCode).where(
                PairingCode.tv_device_id == tv_device_id,
                PairingCode.consumed_at.is_(None),
                PairingCode.expires_at > expiry_time,
            )
        )
        pairing_codes = list(result.scalars().all())
        for pairing_code in pairing_codes:
            pairing_code.expires_at = expiry_time

        if pairing_codes:
            await self.session.flush()
        return len(pairing_codes)

    async def validate_qr_token_and_pin(
        self,
        *,
        qr_token: str,
        pin: str,
        now: datetime | None = None,
    ) -> ValidatedPairing:
        check_time = now or datetime.now(UTC)
        token_hash = self.hash_token(qr_token)
        result = await self.session.execute(
            select(GuestSession, PairingCode)
            .join(PairingCode, GuestSession.pairing_code_id == PairingCode.id)
            .where(GuestSession.qr_token_hash == token_hash)
        )
        row = result.one_or_none()
        if row is None:
            raise PairingValidationError("Invalid pairing credentials")

        guest_session, pairing_code = row
        valid_session_states = {
            GuestSessionState.PIN_DISPLAYED,
            GuestSessionState.PAIRING_PENDING,
        }
        if (
            not self.verify_token(qr_token, guest_session.qr_token_hash)
            or guest_session.expires_at <= check_time
            or guest_session.state not in valid_session_states
            or not self.pairing_code_is_valid(pairing_code, pin, now=check_time)
        ):
            raise PairingValidationError("Invalid or expired pairing credentials")

        pairing_code.consumed_at = check_time
        if guest_session.state == GuestSessionState.PIN_DISPLAYED:
            GuestSessionService.transition_state(
                guest_session,
                GuestSessionState.PAIRING_PENDING,
                now=check_time,
            )
        await self.session.flush()
        return ValidatedPairing(guest_session, pairing_code)
