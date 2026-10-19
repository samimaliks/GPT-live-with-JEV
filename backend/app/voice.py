"""Browser audio in, gpt-live-1 out, with calendar, weather, and web search."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import WebSocket
from openai import AsyncOpenAI

from backend.app.calendar_api import create_event, list_events, move_event
from backend.app.config import TIMEZONE
from backend.app.jev_rank import rank_events
from backend.app.prompt import AGENT_BRIEF, AGENT_PROMPT
from backend.app.jev_judge import JevJudge, TranscriptDebouncer, format_verdict, utterance_ended
from backend.app.meetings import (
    EMAIL_RE,
    cancels_new_event,
    guest_addresses,
    parse_move_event,
    parse_new_event,
    wants_existing_invites,
    wants_guests,
    wants_move_event,
    wants_new_event,
)
from backend.app.weather import WeatherError, current_weather, wants_weather, weather_places

SAMPLE_RATE = 24_000


def session_config() -> dict[str, Any]:
    return {
        "model": "gpt-live-1",
        "instructions": AGENT_PROMPT,
        "audio": {
            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
            "output": {"voice": "marin"},
        },
        "delegation": {
            "type": "responses",
            "responses": {
                "model": "gpt-5.6-luna",
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
            },
        },
    }


def _decision_text(events: list[dict[str, Any]]) -> str:
    now = next((event for event in events if event.get("decision") == "now"), None)
    later = [event for event in events if event.get("decision") == "later"]
    if now is None:
        titles = "; ".join(event["title"] for event in events)
        return (
            "Jev could not rank these events. Read only these titles and times, "
            f"and do not decide which is more important: {titles}"
        )
    later_text = "; ".join(
        f"{event['title']} ({int(float(event.get('score', 0)) * 100)} percent attend soon)"
        for event in later
    ) or "none"
    choice = int(float(now.get("choice") or now.get("score") or 0) * 100)
    return (
        f"Jev's decision: attend now, {now['title']} at {now['start']}, confidence {choice} percent. "
        f"Attend later, in this order: {later_text}. "
        "Read that decision. Do not change it. Do not add events."
    )


async def run_call(ws: WebSocket, owner_email: str) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        await ws.send_json({"type": "error", "text": "OPENAI_API_KEY is missing from .env."})
        return

    send_lock = asyncio.Lock()
    audio_in: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
    guest_in: asyncio.Queue[str] = asyncio.Queue()
    stop = asyncio.Event()
    user_said = ""
    agent_said = ""
    email_seen = False
    end_scheduled = False
    event_open = False
    event_wait = False
    event_saving = False
    event_saved: set[str] = set()
    event_missing = ""
    move_open = False
    move_wait = False
    move_saving = False
    move_done: set[str] = set()
    move_missing = ""
    guests_wanted = False
    guest_box = False
    pending_guests: list[str] = []
    pending_details: dict[str, Any] | None = None
    list_started = False
    weather_wait = False
    weather_done: set[str] = set()
    weather_seq = 0
    search_open = 0
    started = False
    closing = False
    told_closed = False

    async def emit(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def emit_audio(pcm: bytes) -> None:
        if not pcm:
            return
        async with send_lock:
            await ws.send_bytes(pcm)

    async def reader() -> None:
        while not stop.is_set():
            message = await ws.receive()
            kind = message.get("type")
            if kind == "websocket.disconnect":
                stop.set()
                return
            data = message.get("bytes")
            if data:
                try:
                    audio_in.put_nowait(data)
                except asyncio.QueueFull:
                    pass
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "hangup":
                stop.set()
            elif payload.get("type") == "guests":
                await guest_in.put(str(payload.get("emails", "")))

    jev = JevJudge()
    await jev.__aenter__()
    debouncer = TranscriptDebouncer() if jev.enabled else None

    def schedule_jev(fragment: str) -> None:
        if debouncer is None:
            return

        async def score() -> None:
            try:
                verdict = await jev.judge(
                    brief=AGENT_BRIEF,
                    user=user_said,
                    agent=agent_said,
                    email_seen=email_seen,
                )
            except Exception as exc:
                detail = str(exc)
                if "401" in detail or "User not found" in detail:
                    detail = "OpenRouter rejected OPENROUTER_API_KEY (401). Scores are off until the key is fixed."
                await emit({"type": "error", "text": f"Jev scores unavailable: {detail}"})
                return
            if verdict is not None:
                await emit({"type": "jev", "line": format_verdict(verdict)})

        debouncer.push(utterance_ended(fragment), score)

    try:
        async with AsyncOpenAI() as client:
            async with client.live.connect() as connection:

                async def send_audio() -> None:
                    pending = b""
                    while True:
                        chunk = pending + await audio_in.get()
                        complete = len(chunk) - (len(chunk) % 2)
                        pending = chunk[complete:]
                        if complete and started and not closing:
                            await connection.session.input_audio.append(
                                audio=base64.b64encode(chunk[:complete]).decode("ascii")
                            )

                async def hang_up() -> None:
                    nonlocal closing
                    await stop.wait()
                    closing = True
                    await connection.session.close(event_id="event_close")

                async def save_event(details: dict[str, Any], guests: list[str]) -> None:
                    nonlocal event_open, event_saving, guests_wanted, guest_box, pending_details, pending_guests
                    slot = f"{str(details['title']).lower()}|{details['start'].isoformat()}"
                    if slot in event_saved or event_saving:
                        return
                    event_saving = True
                    event_open = True
                    await emit({"type": "status", "text": f"Adding {details['title']} to your calendar..."})
                    try:
                        _link, when = await asyncio.to_thread(
                            create_event,
                            owner_email,
                            str(details["title"]),
                            details["start"],
                            details["end"],
                            guests,
                        )
                    except Exception as exc:
                        event_saving = False
                        await emit({"type": "error", "text": f"The event could not be created: {exc}"})
                        await connection.session.commentary.append(
                            content=(
                                "The event could not be created. Say that. "
                                "Do not say that it was added. Do not ask for an email."
                            ),
                            delegation_id=None,
                            event_id="event_create_failed",
                        )
                        return
                    event_saved.add(slot)
                    event_saving = False
                    event_open = False
                    guests_wanted = False
                    guest_box = False
                    pending_details = None
                    pending_guests = []
                    guest_note = f" Guests: {', '.join(guests)}." if guests else " No guest was added."
                    await emit({"type": "need_email", "open": False})
                    await emit(
                        {
                            "type": "event_created",
                            "text": f"{details['title']} is on your calendar for {when}.{guest_note}",
                        }
                    )
                    await refresh_calendar_panel()
                    if guests:
                        spoken = (
                            f"The event is on their calendar: {details['title']}, {when}, "
                            f"{details['minutes']} minutes, Asia/Karachi. "
                            f"Guests: {', '.join(guests)}. Google will email those guests. "
                            "Confirm the title, the time, and those emails in one short sentence. "
                            "Do not say goodbye."
                        )
                    else:
                        spoken = (
                            f"The event is on their calendar: {details['title']}, {when}, "
                            f"{details['minutes']} minutes, Asia/Karachi. No guest was added. "
                            "Confirm the title and the time in one short sentence. "
                            "Do not ask for an email. Do not say goodbye."
                        )
                    await connection.session.commentary.append(
                        content=spoken,
                        delegation_id=None,
                        event_id="event_created",
                    )

                async def watch_guests() -> None:
                    nonlocal pending_guests
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(guest_in.get(), timeout=0.3)
                        except TimeoutError:
                            continue
                        if not guests_wanted or event_saving:
                            continue
                        found = guest_addresses(raw)
                        typed = EMAIL_RE.findall(raw)
                        if len(typed) > 10:
                            await emit({"type": "error", "text": "Add up to 10 guest emails."})
                            continue
                        if not found or len(found) != len({item.lower() for item in typed}):
                            await emit({"type": "error", "text": "Type normal email addresses, separated by commas."})
                            continue
                        pending_guests = found
                        await connection.session.commentary.append(
                            content=(
                                f"The user typed these guest emails: {', '.join(found)}. "
                                "Read them back once. Do not ask them to say the emails."
                            ),
                            delegation_id=None,
                            event_id="event_guests_typed",
                        )
                        if pending_details is not None:
                            await save_event(pending_details, found)

                async def refresh_calendar_panel() -> tuple[list[dict[str, Any]], str]:
                    try:
                        found = await asyncio.to_thread(list_events, owner_email)
                    except Exception as exc:
                        await emit({"type": "calendar", "phase": "error", "events": [], "error": str(exc)})
                        return [], str(exc)
                    if not found:
                        await emit({"type": "calendar", "phase": "empty", "events": []})
                        return [], ""
                    try:
                        ranked, problem = await rank_events(found)
                    except Exception as exc:
                        ranked, problem = found, str(exc)
                    await emit(
                        {
                            "type": "calendar",
                            "phase": "ready",
                            "events": ranked,
                            "error": problem or "",
                        }
                    )
                    print(
                        f"Calendar ready for {owner_email}: {len(ranked)} event(s)"
                        + (f" ({problem})" if problem else "")
                    )
                    return ranked, problem or ""

                async def save_move(details: dict[str, Any]) -> None:
                    nonlocal move_open, move_saving, move_missing
                    slot = f"{details['id']}|{details['start'].isoformat()}"
                    if slot in move_done or move_saving:
                        return
                    move_saving = True
                    move_open = True
                    await emit({"type": "status", "text": f"Moving {details['title']} on your calendar..."})
                    try:
                        _link, when = await asyncio.to_thread(
                            move_event,
                            owner_email,
                            str(details["id"]),
                            details["start"],
                            details["end"],
                        )
                    except Exception as exc:
                        move_saving = False
                        await emit({"type": "error", "text": f"The event could not be moved: {exc}"})
                        await connection.session.commentary.append(
                            content=(
                                "The event could not be moved. Say that. "
                                "Do not say that it was moved."
                            ),
                            delegation_id=None,
                            event_id="event_move_failed",
                        )
                        return
                    move_done.add(slot)
                    move_saving = False
                    move_open = False
                    move_missing = ""
                    await emit(
                        {
                            "type": "event_created",
                            "text": f"{details['title']} was moved to {when}.",
                        }
                    )
                    await refresh_calendar_panel()
                    await connection.session.commentary.append(
                        content=(
                            f"The event was moved on their calendar: {details['title']}, {when}, "
                            f"{details['minutes']} minutes, Asia/Karachi. "
                            "Confirm the title and the new time in one short sentence. "
                            "Do not say goodbye."
                        ),
                        delegation_id=None,
                        event_id="event_moved",
                    )

                async def speak_calendar() -> None:
                    await emit({"type": "calendar", "phase": "calling", "events": []})
                    await connection.session.commentary.append(
                        content=(
                            "The caller asked for their calendar. Say you are checking it now. "
                            "Wait for Jev's decision before you name any event."
                        ),
                        delegation_id=None,
                        event_id="event_calendar_checking",
                    )
                    ranked, problem = await refresh_calendar_panel()
                    if problem and not ranked:
                        await connection.session.commentary.append(
                            content=(
                                "Their calendar could not be read. Say that. "
                                "Do not invent events."
                            ),
                            delegation_id=None,
                            event_id="event_calendar_failed",
                        )
                        return
                    if not ranked:
                        await connection.session.commentary.append(
                            content="Their calendar has no upcoming events. Say that. Do not invent events.",
                            delegation_id=None,
                            event_id="event_calendar_empty",
                        )
                        return
                    note = _decision_text(ranked)
                    if problem:
                        note = (
                            f"{problem} Still read only these Google Calendar events; "
                            f"do not invent a priority. {_decision_text(ranked)}"
                        )
                    await connection.session.commentary.append(
                        content=note,
                        delegation_id=None,
                        event_id="event_calendar_ranked",
                    )

                async def speak_weather(city: str) -> None:
                    nonlocal weather_seq
                    weather_seq += 1
                    ticket = weather_seq
                    weather_done.add(city.lower())
                    await emit({"type": "weather", "phase": "calling", "city": city})
                    await connection.session.commentary.append(
                        content=(
                            f"The caller asked for the weather in {city}. "
                            "Say you are checking that city now. "
                            "Do not reuse an earlier city's temperature or conditions."
                        ),
                        delegation_id=None,
                        event_id=f"event_weather_checking_{ticket}",
                    )
                    try:
                        result = await asyncio.to_thread(current_weather, city)
                    except Exception as exc:
                        detail = str(exc) if isinstance(exc, WeatherError) else "The weather could not be read."
                        await emit(
                            {
                                "type": "weather",
                                "phase": "error",
                                "city": city,
                                "error": detail,
                            }
                        )
                        await connection.session.commentary.append(
                            content=(
                                f"The weather lookup for {city} failed: {detail} "
                                "Say that. Do not invent a temperature or conditions."
                            ),
                            delegation_id=None,
                            event_id=f"event_weather_failed_{ticket}",
                        )
                        return
                    weather_done.add(result["city"].lower())
                    await emit(
                        {
                            "type": "weather",
                            "phase": "ready",
                            "city": result["city"],
                            "temperature": result["temperature"],
                            "conditions": result["conditions"],
                            "icon": result["icon"],
                        }
                    )
                    await connection.session.commentary.append(
                        content=(
                            f"Weather result: {result['city']}, {result['temperature']}, {result['conditions']}. "
                            "Say only that city, that temperature, and those conditions."
                        ),
                        delegation_id=None,
                        event_id=f"event_weather_ready_{ticket}",
                    )

                await connection.session.start(session=session_config(), event_id="event_start")
                tasks = [
                    asyncio.create_task(reader()),
                    asyncio.create_task(send_audio()),
                    asyncio.create_task(hang_up()),
                    asyncio.create_task(watch_guests()),
                ]
                try:
                    async for event in connection:
                        event_type = getattr(event, "type", "")
                        if event_type == "session.started":
                            started = True
                            await emit({"type": "status", "text": "On the call."})
                            await connection.session.commentary.append(
                                content=(
                                    "Start the call now. Greet them briefly as their personal assistant, "
                                    "then pause."
                                ),
                                delegation_id=None,
                                event_id="event_greet",
                            )
                        elif event_type == "session.output_audio.delta":
                            await emit_audio(base64.b64decode(event.delta))
                        elif event_type == "session.input_transcript.delta":
                            user_said += event.delta
                            if EMAIL_RE.search(user_said):
                                email_seen = True
                            recent = user_said[-500:]
                            heard = user_said[-1200:]
                            if wants_existing_invites(recent) and not list_started:
                                list_started = True
                                asyncio.create_task(speak_calendar())
                            fresh = [city for city in weather_places(heard) if city.lower() not in weather_done]
                            if fresh and not weather_wait:

                                async def maybe_weather() -> None:
                                    nonlocal weather_wait
                                    await asyncio.sleep(1.6)
                                    latest = user_said[-1200:]
                                    cities = [
                                        city
                                        for city in weather_places(latest)
                                        if city.lower() not in weather_done
                                    ]
                                    weather_wait = False
                                    for city in cities:
                                        await speak_weather(city)

                                weather_wait = True
                                asyncio.create_task(maybe_weather())
                            if (event_open or move_open) and cancels_new_event(user_said[-160:]):
                                was_move = move_open and not event_open
                                event_open = False
                                event_missing = ""
                                move_open = False
                                move_missing = ""
                                guests_wanted = False
                                guest_box = False
                                pending_details = None
                                pending_guests = []
                                await emit({"type": "need_email", "open": False})
                                await connection.session.commentary.append(
                                    content=(
                                        "They cancelled moving the event. Do not move it."
                                        if was_move
                                        else "They cancelled the new event. Do not create it. Do not ask for an email."
                                    ),
                                    delegation_id=None,
                                    event_id="event_move_cancelled" if was_move else "event_create_cancelled",
                                )
                            elif wants_move_event(heard) and not move_wait and not move_saving and not event_saving:

                                async def maybe_move() -> None:
                                    nonlocal move_open, move_wait, move_missing
                                    await asyncio.sleep(1.6)
                                    move_wait = False
                                    latest = user_said[-1500:]
                                    if cancels_new_event(latest[-160:]) or not wants_move_event(latest):
                                        if not move_saving:
                                            move_open = False
                                        return
                                    try:
                                        found = await asyncio.to_thread(list_events, owner_email)
                                    except Exception as exc:
                                        await emit({"type": "error", "text": f"The calendar could not be read: {exc}"})
                                        await connection.session.commentary.append(
                                            content=(
                                                "Their calendar could not be read, so the event was not moved. "
                                                "Say that. Do not invent a new time."
                                            ),
                                            delegation_id=None,
                                            event_id="event_move_list_failed",
                                        )
                                        return
                                    details, missing = parse_move_event(
                                        latest,
                                        datetime.now(ZoneInfo(TIMEZONE)),
                                        found,
                                    )
                                    if details is None:
                                        move_open = True
                                        key = ", ".join(missing)
                                        if key == move_missing:
                                            return
                                        move_missing = key
                                        await connection.session.commentary.append(
                                            content=(
                                                "The user wants to move an existing calendar event. "
                                                f"These details are still missing: {key}. "
                                                "Ask only for those details. "
                                                "Do not say the event was moved yet."
                                            ),
                                            delegation_id=None,
                                            event_id="event_move_need_details",
                                        )
                                        return
                                    move_missing = ""
                                    await save_move(details)

                                move_wait = True
                                move_open = True
                                asyncio.create_task(maybe_move())
                            elif wants_new_event(heard) and not event_wait and not event_saving and not move_open:

                                async def maybe_create() -> None:
                                    nonlocal event_open, event_wait, event_missing, guests_wanted, guest_box, pending_details
                                    await asyncio.sleep(1.6)
                                    event_wait = False
                                    latest = user_said[-1500:]
                                    if cancels_new_event(latest[-160:]) or not wants_new_event(latest):
                                        if not event_saving:
                                            event_open = False
                                        return
                                    if wants_guests(latest):
                                        guests_wanted = True
                                    details, missing = parse_new_event(latest, datetime.now(ZoneInfo(TIMEZONE)))
                                    if guests_wanted and not guest_box:
                                        guest_box = True
                                        event_open = True
                                        await emit({"type": "need_email", "open": True})
                                        await connection.session.commentary.append(
                                            content=(
                                                "They asked to add guests. Ask them to type the guest emails "
                                                "into the box and press Enter. More than one email can be separated by commas. "
                                                "Do not ask them to say the emails. Do not say the event was created."
                                            ),
                                            delegation_id=None,
                                            event_id="event_ask_guests",
                                        )
                                    if details is None:
                                        event_open = True
                                        key = ", ".join(missing)
                                        if key == event_missing:
                                            return
                                        event_missing = key
                                        await connection.session.commentary.append(
                                            content=(
                                                "The user wants an event on their own calendar. "
                                                f"These details are still missing: {key}. "
                                                "Ask only for those details. "
                                                "Do not ask for an email unless they asked to add guests. "
                                                "The event is not on the calendar yet. Do not say you have everything."
                                            ),
                                            delegation_id=None,
                                            event_id="event_need_details",
                                        )
                                        return
                                    event_missing = ""
                                    if guests_wanted and not pending_guests:
                                        pending_details = details
                                        return
                                    await save_event(details, pending_guests if guests_wanted else [])

                                event_wait = True
                                event_open = True
                                asyncio.create_task(maybe_create())
                            if (
                                not end_scheduled
                                and not event_open
                                and not move_open
                                and re.search(r"\b(bye|goodbye)\b", user_said[-60:].lower())
                            ):
                                end_scheduled = True

                                async def finish_after_user_bye() -> None:
                                    await asyncio.sleep(1.2)
                                    stop.set()

                                asyncio.create_task(finish_after_user_bye())
                            await emit({"type": "transcript", "user": user_said, "agent": agent_said})
                            schedule_jev(event.delta)
                        elif event_type == "session.output_transcript.delta":
                            agent_said += event.delta
                            await emit({"type": "transcript", "user": user_said, "agent": agent_said})
                            schedule_jev(event.delta)
                        elif event_type == "session.delegation.created":
                            delegation = getattr(event, "delegation", None)
                            target = getattr(delegation, "target", "") if delegation is not None else ""
                            if target == "responses":
                                search_open += 1
                                await emit({"type": "search", "phase": "searching"})
                        elif event_type == "response.event":
                            nested = getattr(event, "event", None)
                            nested_type = ""
                            if isinstance(nested, dict):
                                nested_type = str(nested.get("type") or "")
                            elif nested is not None:
                                nested_type = str(getattr(nested, "type", "") or "")
                            if nested_type in {"response.completed", "response.failed", "response.incomplete"}:
                                search_open = max(0, search_open - 1)
                                if search_open == 0:
                                    await emit({"type": "search", "phase": "idle"})
                        elif event_type == "session.closed":
                            told_closed = True
                            await emit({"type": "closed", "text": "Call ended."})
                            break
                        elif event_type == "error":
                            detail = event.model_dump_json() if hasattr(event, "model_dump_json") else str(event)
                            await emit({"type": "error", "text": detail})
                finally:
                    stop.set()
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if debouncer is not None:
            await debouncer.close()
        await jev.__aexit__(None, None, None)
        if not told_closed:
            try:
                await emit({"type": "closed", "text": "Call ended."})
            except Exception:
                pass
