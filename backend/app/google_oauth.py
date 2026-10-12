"""Google OAuth for each person's own calendar."""

from __future__ import annotations

import base64
import json
import os
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from backend.app.config import REDIRECT_URI, ROOT, SCOPES, TOKENS

_pending: dict[str, str | None] = {}


def _client_config() -> dict:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env. "
            "Create an OAuth web client in Google Cloud and add redirect "
            f"{REDIRECT_URI}."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }


def _flow() -> Flow:
    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)


def authorization_url() -> str:
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending[state] = flow.code_verifier
    return url


def _email_from_credentials(creds: Credentials) -> str:
    token = getattr(creds, "id_token", None)
    if isinstance(token, str) and token.count(".") == 2:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        email = str(data.get("email", "")).strip().lower()
        if email:
            return email
    request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        info = json.loads(response.read().decode("utf-8"))
    email = str(info.get("email", "")).strip().lower()
    if not email:
        raise RuntimeError("Google did not return an email for this account.")
    return email


def _token_path(email: str):
    safe = email.replace("@", "_at_").replace(".", "_")
    return TOKENS / f"{safe}.json"


def finish_login(code: str, state: str) -> str:
    if state not in _pending:
        raise RuntimeError("This Google sign-in expired. Start it again from the page.")
    verifier = _pending.pop(state)
    flow = _flow()
    flow.code_verifier = verifier
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow.fetch_token(code=code)
    creds = flow.credentials
    email = _email_from_credentials(creds)
    TOKENS.mkdir(parents=True, exist_ok=True)
    _token_path(email).write_text(creds.to_json(), encoding="utf-8")
    return email


def credentials_for(email: str) -> Credentials:
    path = _token_path(email)
    if not path.is_file():
        raise FileNotFoundError("This Google account is not connected.")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError("The Google sign-in expired. Connect the calendar again.")
    return creds
