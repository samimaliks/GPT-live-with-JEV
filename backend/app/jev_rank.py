"""Jev chooses which calendar event to attend now."""

from __future__ import annotations

from typing import Any

from typesafe_sdk import Choice, Noul

from backend.app.jev_client import open_client


def _describe(event: dict[str, Any]) -> str:
    guests = ", ".join(event.get("guests") or []) or "no guests listed"
    return f"{event.get('title')} from {event.get('start')} to {event.get('end')}. Guests: {guests}"


async def rank_events(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Return events with decision and score. The error is set when Jev cannot decide."""
    if not events:
        return [], None
    opened = await open_client()
    if opened is None:
        return events, "Jev is off, so these events were not ranked."
    client, model = opened
    keys = [f"e{index}" for index in range(len(events))]
    criteria = {key: _describe(event) for key, event in zip(keys, events)}
    questions: dict[str, Any] = {
        "attend_now": Choice(
            instructions=(
                "Which single event should this person attend first? "
                "Use only the title, time, and guests."
            ),
            criteria=criteria,
        )
    }
    for key, text in criteria.items():
        questions[f"soon_{key}"] = Noul(
            instructions=f"Should this event be attended soon rather than postponed? {text}"
        )
    try:
        response = await client.system_one({"events": criteria}, questions, model=model)
    except Exception as exc:
        await client.__aexit__(None, None, None)
        return events, _rank_error(exc)
    try:
        chosen = response.choices["attend_now"].choice
        chosen_p = float(response.choices["attend_now"].probabilities.get(chosen, 0.0))
        ranked: list[dict[str, Any]] = []
        for key, event in zip(keys, events):
            row = dict(event)
            row["score"] = float(response.nouls[f"soon_{key}"].noul)
            row["decision"] = "now" if key == chosen else "later"
            if key == chosen:
                row["choice"] = chosen_p
            ranked.append(row)
        now = [row for row in ranked if row["decision"] == "now"]
        later = sorted(
            (row for row in ranked if row["decision"] != "now"),
            key=lambda row: row["score"],
            reverse=True,
        )
        if not now and ranked:
            ranked[0]["decision"] = "now"
            now = [ranked[0]]
            later = [row for row in ranked if row is not now[0]]
        return now + later, None
    finally:
        await client.__aexit__(None, None, None)


def _rank_error(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if "401" in text or "user not found" in low or "unauthorized" in low:
        return (
            "Jev ranking failed: OpenRouter rejected the API key. "
            "Put a valid OPENROUTER_API_KEY in .env, or use TYPESAFE_API_KEY."
        )
    return f"Jev ranking failed: {text}"
