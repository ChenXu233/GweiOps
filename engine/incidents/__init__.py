# engine/incidents/__init__.py
"""事故报告:一次事故的经过与结论。"""

from .store import (
    STATUS_CLOSED,
    STATUS_OPEN,
    DbIncidentStore,
    IncidentStore,
    JsonlIncidentStore,
    create_incident_store,
    ensure_schema,
)

__all__ = [
    "IncidentStore",
    "JsonlIncidentStore",
    "DbIncidentStore",
    "create_incident_store",
    "ensure_schema",
    "STATUS_OPEN",
    "STATUS_CLOSED",
]
