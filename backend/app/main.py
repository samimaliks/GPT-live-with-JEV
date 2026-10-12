"""API for the personal assistant page."""

from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv
from typing import Annotated

from fastapi import FastAPI, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from backend.app.config import FRONTEND_ORIGIN, ROOT
from backend.app.google_oauth import authorization_url, finish_login
from backend.app.sessions import close_session, email_for, open_session
from backend.app.voice import run_call

# override=True so a new key in .env wins over a stale shell env var.
load_dotenv(ROOT / ".env", override=True)

app = FastAPI(title="Personal agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_id(header: str | None, query: str | None) -> str | None:
    return header or query or None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
def me(
    session: str | None = None,
    x_session: Annotated[str | None, Header()] = None,
) -> dict:
    email = email_for(_session_id(x_session, session))
    if not email:
        return {"connected": False, "email": ""}
    return {"connected": True, "email": email}


@app.get("/api/auth/google")
def google_start() -> RedirectResponse:
    try:
        return RedirectResponse(authorization_url())
    except Exception as exc:
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?auth_error={quote(str(exc))}")


@app.get("/api/auth/google/callback")
def google_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    if error or not code:
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?auth_error={quote(error or 'Google sign-in was cancelled.')}")
    try:
        email = finish_login(code, state)
    except Exception as exc:
        return RedirectResponse(f"{FRONTEND_ORIGIN}/?auth_error={quote(str(exc))}")
    sid = open_session(email)
    return RedirectResponse(f"{FRONTEND_ORIGIN}/?session={quote(sid)}")


@app.post("/api/auth/logout")
def logout(
    session: str | None = None,
    x_session: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    close_session(_session_id(x_session, session))
    return {"ok": True}


@app.websocket("/api/call")
async def call(ws: WebSocket) -> None:
    await ws.accept()
    email = email_for(ws.query_params.get("session"))
    if not email:
        await ws.send_json({"type": "error", "text": "Connect Google Calendar before starting the call."})
        await ws.close()
        return
    if not os.environ.get("OPENAI_API_KEY"):
        await ws.send_json({"type": "error", "text": "OPENAI_API_KEY is missing from .env."})
        await ws.close()
        return
    await run_call(ws, email)
