"""Open a Jev client. Ranking and transcript scores stay separate."""

from __future__ import annotations

import os

from typesafe_sdk import AsyncTypeSafeClient

OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_MODEL = "jev-1.13"
TYPESAFE_MODEL = "jev-latest"


def jev_model() -> tuple[str, str, str] | None:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        return openrouter_key, OPENROUTER_BASE_URL, OPENROUTER_MODEL
    typesafe_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if typesafe_key:
        return typesafe_key, "", TYPESAFE_MODEL
    return None


async def open_client() -> tuple[AsyncTypeSafeClient, str] | None:
    found = jev_model()
    if found is None:
        return None
    key, base_url, model = found
    if base_url:
        client = AsyncTypeSafeClient(api_key=key, base_url=base_url, model=model)
    else:
        client = AsyncTypeSafeClient(api_key=key, model=model)
    await client.__aenter__()
    return client, model
