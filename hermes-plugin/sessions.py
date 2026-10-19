"""Companion session service: list Hermes sessions from inside a Hermes process.

The side panel needs a label and an identity per session, nothing else. Hermes session rows carry
working directories, git roots, token counts and costs; this module projects them down to the
handful of fields the panel shows (``ALLOWED_FIELDS``) before anything leaves the process.

Two listing strategies, tried in order, each wrapped so a Hermes-internal change can never raise
into the broker loop or into Hermes itself:

1. Hermes' own aggregated listing — the function behind ``GET /api/profiles/sessions``.
2. A direct read-only ``SessionDB`` read of every profile's ``state.db``.

This module has no package-relative imports so it can be exercised standalone in tests.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

ALLOWED_FIELDS = ("id", "profile", "title", "display_name", "source", "last_active", "is_active")
MAX_SESSIONS = 200
MAX_TEXT = 200
MAX_ERROR = 300

Listing = Callable[[int], Iterable[Any]]


def _text(value: Any, limit: int = MAX_TEXT) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def project_session(row: Any) -> Optional[dict]:
    """Return the panel-facing view of one Hermes session row, or None when unusable."""

    if not isinstance(row, dict):
        return None
    session_id = _text(row.get("id"))
    if not session_id:
        return None
    return {
        "id": session_id,
        "profile": _text(row.get("profile")) or "default",
        "title": _text(row.get("title")),
        "display_name": _text(row.get("display_name")),
        "source": _text(row.get("source"), 40),
        "last_active": _number(row.get("last_active")),
        "is_active": bool(row.get("is_active")),
    }


def project_sessions(rows: Iterable[Any], limit: int = MAX_SESSIONS) -> list[dict]:
    projected: list[dict] = []
    cap = min(max(int(limit), 1), MAX_SESSIONS)
    for row in rows:
        item = project_session(row)
        if item is None:
            continue
        projected.append(item)
        if len(projected) >= cap:
            break
    return projected


# ---- listing strategies (Hermes-internal, wrapped) -----------------------------------------------

def hermes_aggregated_listing(limit: int) -> list[Any]:
    """Hermes' multi-profile session listing (same code path as the web dashboard API)."""

    from hermes_cli.web_routers import profiles as profiles_router  # type: ignore[import-not-found]

    payload = profiles_router.get_profiles_sessions(
        limit=limit, offset=0, min_messages=0, archived="exclude", order="recent", profile="all",
    )
    rows = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("unexpected session listing shape")
    return rows


def direct_state_db_listing(limit: int) -> list[Any]:
    """Read every profile's state.db read-only when the aggregated listing is unavailable."""

    from hermes_cli import profiles as profiles_mod  # type: ignore[import-not-found]
    from hermes_state import SessionDB  # type: ignore[import-not-found]

    targets = list(profiles_mod.profiles_to_serve(
        multiplex=True, include_standalone=True, include_parked=True,
    ))
    merged: list[dict] = []
    for name, home in targets:
        db_path = home / "state.db"
        if not db_path.is_file():
            continue
        try:
            db = SessionDB(db_path, read_only=True)
            rows = db.list_sessions_rich(
                limit=limit, offset=0, order_by_last_active=True, compact_rows=True,
            )
        except Exception:
            continue
        for row in rows:
            if isinstance(row, dict):
                row.setdefault("profile", name)
                merged.append(row)
    merged.sort(key=lambda row: row.get("last_active") or row.get("started_at") or 0, reverse=True)
    return merged


def list_sessions(limit: int, *, hermes_listing: Optional[Listing] = None,
                  fallback_listing: Optional[Listing] = None) -> dict:
    """Return ``{"ok": True, "data": {...}}`` or ``{"ok": False, "error": ...}`` — never raise."""

    try:
        cap = min(max(int(limit), 1), MAX_SESSIONS)
    except (TypeError, ValueError):
        cap = MAX_SESSIONS
    strategies = (
        ("hermes-api", hermes_listing or hermes_aggregated_listing),
        ("state-db", fallback_listing or direct_state_db_listing),
    )
    failures: list[str] = []
    for source, listing in strategies:
        try:
            rows = listing(cap)
        except Exception as exc:  # noqa: BLE001 - every failure is reported, none propagates
            failures.append(f"{source}: {type(exc).__name__}")
            continue
        return {"ok": True, "data": {"sessions": project_sessions(rows, cap), "source": source}}
    detail = "; ".join(failures) or "no listing strategy available"
    return {"ok": False, "error": f"the Hermes session store could not be read ({detail})"[:MAX_ERROR]}
