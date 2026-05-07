"""
Local-first audit logging for state-changing operations.
Writes to the audit_log table for traceability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from database.engine import SessionLocal
from database.models import AuditLog


def record_audit_event(
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    detail: Optional[str] = None,
    event_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a state-changing operation to the audit log.

    Parameters
    ----------
    action : str
        The operation performed (e.g. "config_update", "trade_execute",
        "data_reset", "secret_save", "secret_clear").
    resource : str
        The affected resource type (e.g. "config", "trade", "alpaca_secret").
    resource_id : str, optional
        The specific ID of the affected resource.
    detail : str, optional
        Human-readable detail about the operation.
    event_metadata : dict, optional
        Additional structured context (e.g. before/after state).
    """
    try:
        db = SessionLocal()
        try:
            entry = AuditLog(
                action=action,
                resource=resource,
                resource_id=resource_id,
                detail=detail,
                event_metadata=event_metadata or {},
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"Audit log write failed (non-fatal): {exc}")
