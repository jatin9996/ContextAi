import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AUDIT_METADATA_KEYS
from app.core.logging import trace_id_var
from app.models import AuditEvent


def clean_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    cleaned: dict = {}
    for key in AUDIT_METADATA_KEYS:
        if key not in metadata or metadata[key] is None:
            continue
        value = metadata[key]
        if isinstance(value, uuid.UUID):
            cleaned[key] = str(value)
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value if not isinstance(value, str) else value[:200]
    return cleaned


async def record_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id_var.get() or None,
            details=clean_metadata(metadata),
        )
    )
