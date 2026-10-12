"""One server session per signed-in Google account."""

from __future__ import annotations

import json
import secrets
import threading

from backend.app.config import DATA, SESSIONS

_lock = threading.Lock()


def _load() -> dict[str, str]:
    if not SESSIONS.is_file():
        return {}
    try:
        raw = json.loads(SESSIONS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(rows: dict[str, str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    SESSIONS.write_text(json.dumps(rows), encoding="utf-8")


def open_session(email: str) -> str:
    sid = secrets.token_urlsafe(32)
    with _lock:
        rows = _load()
        rows[sid] = email.strip().lower()
        _save(rows)
    return sid


def email_for(sid: str | None) -> str | None:
    if not sid:
        return None
    with _lock:
        email = _load().get(sid)
    return email if isinstance(email, str) and email else None


def close_session(sid: str | None) -> None:
    if not sid:
        return
    with _lock:
        rows = _load()
        rows.pop(sid, None)
        _save(rows)
