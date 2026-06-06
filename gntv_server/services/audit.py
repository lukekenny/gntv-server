from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import AuditEvent

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)


def sanitize_audit_metadata(value: Any, *, key: str | None = None) -> Any:
    if key is not None:
        normalized_key = key.casefold().replace("-", "_")
        if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
            return REDACTED

    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_audit_metadata(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_audit_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_audit_metadata(item) for item in value]
    if isinstance(value, str) and value.casefold().startswith("bearer "):
        return REDACTED
    return value


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(
        self,
        *,
        actor_type: str,
        event_type: str,
        property_id: UUID | None = None,
        actor_id: str | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        ip_address: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            property_id=property_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            metadata_=sanitize_audit_metadata(metadata or {}),
        )
        self.session.add(event)
        await self.session.flush()
        return event
