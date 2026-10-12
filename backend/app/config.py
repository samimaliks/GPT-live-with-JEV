"""Shared paths and OAuth settings for the Vite app."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TOKENS = DATA / "tokens"
SESSIONS = DATA / "sessions.json"
REDIRECT_URI = "http://localhost:8000/api/auth/google/callback"
FRONTEND_ORIGIN = "http://localhost:5173"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
]
TIMEZONE = "Asia/Karachi"
MEETING_TITLE = "Meeting"
