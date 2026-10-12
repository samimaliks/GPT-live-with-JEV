"""Talk to gpt-live-1 from this machine.

The Live API is a voice session, not a chat-completions call. This script
opens the microphone, streams PCM16 audio to wss://api.openai.com/v1/live/sessions,
and plays the model's speech on the default speakers.

Setup (PowerShell, from this folder):

    copy .env.example .env
    # put your key in .env
    .\\.venv\\Scripts\\python.exe live_voice.py --list-devices
    .\\.venv\\Scripts\\python.exe live_voice.py

Voice time is billed at $0.05 per minute, per second. Ctrl+C ends the session.
Use headphones so the microphone does not hear the assistant.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import asyncio
import base64
import os
import re
import signal
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from openai import AsyncOpenAI

from calendar_invite import (
    MEETING_TITLE,
    TIMEZONE,
    create_invite,
    list_upcoming_invites,
    meeting_minutes,
    meeting_window,
    wants_calendar_invite,
    wants_existing_invites,
)
from backend.app.jev_judge import JevJudge, TranscriptDebouncer, format_verdict, utterance_ended

SAMPLE_RATE = 24_000
CHANNELS = 1
BLOCK_FRAMES = 2_400  # 100 ms at 24 kHz


def list_devices() -> None:
    print(sd.query_devices())
    default_in, default_out = sd.default.device
    print(f"\nDefault input device: {default_in}")
    print(f"Default output device: {default_out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local microphone session with gpt-live-1")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--input-device", type=int, default=None, help="sounddevice input index")
    parser.add_argument("--output-device", type=int, default=None, help="sounddevice output index")
    parser.add_argument("--voice", default="marin", help="Built-in voice. Default: marin")
    parser.add_argument(
        "--web-search",
        action="store_true",
        help="Delegate current-information questions to a Responses model with web search",
    )
    parser.add_argument(
        "--backend-model",
        default="gpt-5.6-luna",
        help="Responses model used with --web-search. Default: gpt-5.6-luna",
    )
    parser.add_argument(
        "--jev",
        action="store_true",
        help="Score transcripts with Jev. Does not change the voice",
    )
    return parser.parse_args()


CONFERENCE_BRIEF = """Personal assistant on a live voice call.
Speak only calendar decisions, weather results, and web search results the system has already given you.
Do not invent events, weather, or search results."""

SALES_PROMPT = """You are the user's personal assistant on a live voice call.

Help with their calendar, the weather, current questions, and ordinary requests.
Keep each turn short.
Handle interruptions naturally.
If they ask what invites already exist, or for a list of calendar invites, say you are checking their calendar and wait.
You will be told that list. Read only those events. If told there are none, or that the lookup failed, say that. Do not invent meetings and do not ask for an email.
If they ask to book a meeting or send a calendar invite, and they are not asking for an existing list, ask them to type the guest email into the box on the screen and press Enter.
Do not ask them to say or spell the email.
Do not say the invite was sent until you are told it went out.
When you are told it went out, confirm the email and the time in one short sentence. Do not say goodbye.
The call ends only when the user says bye. Until then, stay on the line and answer them.
If they interrupt while you are speaking, stop and respond to what they said.
If you do not know something, say so instead of inventing an answer.
Speak in natural English.
Use short sentences.
Allow small pauses.
Do not speak for too long without giving the other person a chance to respond.
"""


def session_config(args: argparse.Namespace) -> dict[str, Any]:
    if args.web_search:
        delegation: dict[str, Any] = {
            "type": "responses",
            "responses": {
                "model": args.backend_model,
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
            },
        }
    else:
        delegation = {"type": "client"}

    return {
        "model": "gpt-live-1",
        "instructions": SALES_PROMPT,
        "audio": {
            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
            "output": {"voice": args.voice},
        },
        "delegation": delegation,
    }


class Speaker:
    def __init__(self, device: int | None) -> None:
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=device,
            blocksize=BLOCK_FRAMES,
            callback=self._callback,
        )

    def start(self) -> None:
        self._stream.start()

    def push(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            self._buffer.extend(pcm)

    def pending_bytes(self) -> int:
        with self._lock:
            return len(self._buffer)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()

    def _callback(self, outdata: np.ndarray, frames: int, _time: Any, status: sd.CallbackFlags) -> None:
        if status:
            print(f"\n[audio] {status}", file=sys.stderr)
        need = frames * 2
        with self._lock:
            take = min(len(self._buffer), need)
            chunk = bytes(self._buffer[:take])
            del self._buffer[:take]
        if take < need:
            chunk += b"\x00" * (need - take)
        outdata[:] = np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1)


class Transcript:
    def __init__(self) -> None:
        self._who: str | None = None

    def add(self, who: str, text: str) -> None:
        if not text:
            return
        if who != self._who:
            if self._who is not None:
                print()
            print(f"{who}: ", end="", flush=True)
            self._who = who
        print(text, end="", flush=True)

    def finish(self) -> None:
        if self._who is not None:
            print()
            self._who = None


class EmailInbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._email = ""
        self._ready = threading.Event()

    def submit(self, email: str) -> None:
        with self._lock:
            self._email = email.strip()
        self._ready.set()

    def take(self) -> str | None:
        if not self._ready.is_set():
            return None
        self._ready.clear()
        with self._lock:
            email = self._email
            self._email = ""
        return email or None


async def run(
    args: argparse.Namespace,
    sink: Callable[[dict[str, Any]], None] | None = None,
    hangup: threading.Event | None = None,
    inbox: EmailInbox | None = None,
) -> None:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is missing. Copy .env.example to .env and put your OpenAI key there."
        )

    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    stop = asyncio.Event()
    closing = False
    started = False

    def enqueue(payload: bytes) -> None:
        try:
            audio_queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def mic_callback(indata: np.ndarray, _frames: int, _time: Any, status: sd.CallbackFlags) -> None:
        if status:
            print(f"\n[mic] {status}", file=sys.stderr)
        loop.call_soon_threadsafe(enqueue, indata.tobytes())

    speaker = Speaker(args.output_device)
    mic = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        device=args.input_device,
        blocksize=BLOCK_FRAMES,
        callback=mic_callback,
    )
    transcript = Transcript()
    user_said = ""
    agent_said = ""
    email_seen = False
    end_scheduled = False
    invite_requested = False
    invite_wait_scheduled = False
    invite_sent = False
    list_started = False
    email_pattern = re.compile(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|[\w.+-]+\s+at\s+[\w-]+\s+dot\s+[A-Za-z]{2,}",
        re.IGNORECASE,
    )
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, lambda *_sig, _frame: loop.call_soon_threadsafe(stop.set))

    def emit(event: dict[str, Any]) -> None:
        if sink is not None:
            sink(event)

    jev: JevJudge | None = None
    debouncer: TranscriptDebouncer | None = None
    if args.jev:
        jev = JevJudge()
        await jev.__aenter__()
        if jev.enabled:
            debouncer = TranscriptDebouncer()
            print("Jev is scoring transcripts only. Speech is unchanged.")
            emit({"type": "status", "text": "Jev is scoring transcripts only. Speech is unchanged."})
        else:
            emit({"type": "status", "text": "Jev is off for this call. The voice session still runs."})

    def schedule_jev(fragment: str) -> None:
        if debouncer is None or jev is None:
            return

        async def score() -> None:
            try:
                verdict = await jev.judge(
                    brief=CONFERENCE_BRIEF,
                    user=user_said,
                    agent=agent_said,
                    email_seen=email_seen,
                )
            except Exception as exc:
                print(f"\n[jev] {exc}", file=sys.stderr)
                emit({"type": "error", "text": f"Jev: {exc}"})
                return
            if verdict is not None:
                line = format_verdict(verdict)
                print(f"\n{line}", file=sys.stderr)
                emit({"type": "jev", "line": line, "verdict": verdict})

        debouncer.push(utterance_ended(fragment), score)

    print("Connecting to gpt-live-1. Voice time bills at $0.05 per minute.")
    print("Use headphones. Press Ctrl+C to hang up.\n")
    emit({"type": "status", "text": "Connecting. Use headphones so the mic does not hear the rep."})

    async def watch_hangup() -> None:
        if hangup is None:
            return
        while not hangup.is_set():
            await asyncio.sleep(0.2)
        stop.set()

    speaker.start()
    mic.start()
    try:
        async with AsyncOpenAI() as client:
            async with client.live.connect() as connection:

                async def send_audio() -> None:
                    pending = b""
                    while True:
                        chunk = pending + await audio_queue.get()
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
                    print("\nClosing session...")
                    await connection.session.close(event_id="event_close")

                async def send_calendar_invite(email: str) -> None:
                    nonlocal invite_sent
                    if invite_sent:
                        return
                    invite_sent = True
                    minutes = meeting_minutes(user_said)
                    start, end, when = meeting_window(minutes)
                    emit({"type": "status", "text": f"Sending a calendar invite to {email}..."})
                    try:
                        link = await asyncio.to_thread(
                            create_invite,
                            email=email,
                            start=start,
                            end=end,
                            title=MEETING_TITLE,
                            timezone=TIMEZONE,
                        )
                    except Exception as exc:
                        invite_sent = False
                        print(f"\n[calendar] {exc}", file=sys.stderr)
                        emit({"type": "error", "text": f"Calendar invite failed: {exc}"})
                        await connection.session.commentary.append(
                            content=(
                                "The calendar invite could not be sent. "
                                "Do not say that it was sent. Say you will confirm it."
                            ),
                            delegation_id=None,
                            event_id="event_invite_failed",
                        )
                        return
                    print(f"\nInvite sent to {email}: {link}")
                    emit({"type": "invite_sent", "text": f"Calendar invite sent to {email} for {when}."})
                    await connection.session.commentary.append(
                        content=(
                            f"The calendar invite is sent to {email} for {when}, "
                            f"Asia/Karachi, {minutes} minutes. "
                            "Read that email back and confirm the time in one short sentence. "
                            "Do not say goodbye. Wait until the caller says bye."
                        ),
                        delegation_id=None,
                        event_id="event_invite_sent",
                    )

                async def speak_organizer_invites() -> None:
                    emit({"type": "status", "text": "Checking the organizer calendar..."})
                    try:
                        lines = await asyncio.to_thread(list_upcoming_invites)
                    except Exception as exc:
                        print(f"\n[calendar] {exc}", file=sys.stderr)
                        emit({"type": "error", "text": f"Could not read the organizer calendar: {exc}"})
                        await connection.session.commentary.append(
                            content=(
                                "The organizer calendar could not be read. "
                                "Say you cannot see the list right now. "
                                "Do not invent invites. Do not ask for an email."
                            ),
                            delegation_id=None,
                            event_id="event_calendar_list_failed",
                        )
                        return
                    if not lines:
                        emit({"type": "status", "text": "The organizer calendar has no upcoming events."})
                        await connection.session.commentary.append(
                            content=(
                                "The organizer calendar has no upcoming events. "
                                "Say that clearly. Do not invent invites. Do not ask for an email."
                            ),
                            delegation_id=None,
                            event_id="event_calendar_list_empty",
                        )
                        return
                    summary = " ".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))
                    emit({"type": "status", "text": "Organizer calendar: " + "; ".join(lines)})
                    await connection.session.commentary.append(
                        content=(
                            "The organizer calendar has these upcoming events. "
                            "Read each one in a short sentence. Do not add any event. Do not ask for an email. "
                            + summary
                        ),
                        delegation_id=None,
                        event_id="event_calendar_list",
                    )

                async def watch_inbox() -> None:
                    if inbox is None:
                        return
                    while not stop.is_set():
                        typed = inbox.take()
                        if typed and not invite_sent:
                            await connection.session.commentary.append(
                                content=(
                                    f"The caller typed this email into the box: {typed}. "
                                    "Read it back once, and say you are sending the calendar invite now."
                                ),
                                delegation_id=None,
                                event_id="event_email_typed",
                            )
                            await send_calendar_invite(typed)
                        await asyncio.sleep(0.3)

                await connection.session.start(session=session_config(args), event_id="event_start")
                sender = asyncio.create_task(send_audio())
                closer = asyncio.create_task(hang_up())
                watcher = asyncio.create_task(watch_hangup())
                inbox_watcher = asyncio.create_task(watch_inbox())
                try:
                    async for event in connection:
                        event_type = getattr(event, "type", "")
                        if event_type == "session.started":
                            started = True
                            session_id = getattr(getattr(event, "session", None), "id", "")
                            print(f"Session ready {session_id}")
                            print("You are the decision-maker. The rep will open the call.\n")
                            emit({"type": "status", "text": "On the call. You are the decision-maker."})
                            await connection.session.commentary.append(
                                content=(
                                    "Start the call now. Introduce yourself briefly, "
                                    "Greet them briefly as their personal assistant, then pause."
                                ),
                                delegation_id=None,
                                event_id="event_greet",
                            )
                        elif event_type == "session.output_audio.delta":
                            speaker.push(base64.b64decode(event.delta))
                        elif event_type == "session.input_transcript.delta":
                            transcript.add("You", event.delta)
                            user_said += event.delta
                            if email_pattern.search(user_said):
                                email_seen = True
                            recent = user_said[-500:]
                            if wants_existing_invites(recent) and not list_started:
                                list_started = True
                                asyncio.create_task(speak_organizer_invites())
                            if (
                                not invite_requested
                                and not invite_wait_scheduled
                                and wants_calendar_invite(recent)
                            ):
                                invite_wait_scheduled = True

                                async def maybe_ask_email() -> None:
                                    nonlocal invite_requested, invite_wait_scheduled
                                    await asyncio.sleep(1.6)
                                    latest = user_said[-500:]
                                    if not wants_calendar_invite(latest):
                                        invite_wait_scheduled = False
                                        return
                                    if invite_requested:
                                        return
                                    invite_requested = True
                                    emit({"type": "need_email"})
                                    await connection.session.commentary.append(
                                        content=(
                                            "The caller asked to send a calendar invite. "
                                            "Ask them to type their email into the box on the screen and press Enter. "
                                            "Do not ask them to say or spell the email. Then wait."
                                        ),
                                        delegation_id=None,
                                        event_id="event_ask_email",
                                    )

                                asyncio.create_task(maybe_ask_email())
                            if (
                                not end_scheduled
                                and (not invite_requested or invite_sent)
                                and re.search(r"\b(bye|goodbye)\b", user_said[-60:].lower())
                            ):
                                end_scheduled = True

                                async def finish_after_user_bye() -> None:
                                    await asyncio.sleep(1.2)
                                    print("\nYou said bye. Ending the call.")
                                    stop.set()

                                asyncio.create_task(finish_after_user_bye())
                            emit({"type": "transcript", "user": user_said, "agent": agent_said})
                            schedule_jev(event.delta)
                        elif event_type == "session.output_transcript.delta":
                            transcript.add("GPT", event.delta)
                            agent_said += event.delta
                            emit({"type": "transcript", "user": user_said, "agent": agent_said})
                            schedule_jev(event.delta)
                        elif event_type == "session.closed":
                            transcript.finish()
                            print(f"Session closed. Usage: {getattr(event, 'usage', None)}")
                            emit({"type": "closed", "text": "Call ended."})
                            break
                        elif event_type == "error":
                            transcript.finish()
                            detail = event.model_dump_json() if hasattr(event, "model_dump_json") else event
                            print(f"\nError: {detail}", file=sys.stderr)
                            emit({"type": "error", "text": str(detail)})
                        elif event_type not in {
                            "session.commentary.appended",
                            "session.updated",
                        }:
                            # Keep backend and lifecycle events visible without dumping audio.
                            print(f"\n[{event_type}]", file=sys.stderr)
                finally:
                    sender.cancel()
                    closer.cancel()
                    watcher.cancel()
                    inbox_watcher.cancel()
                    await asyncio.gather(sender, closer, watcher, inbox_watcher, return_exceptions=True)
    finally:
        transcript.finish()
        mic.stop()
        mic.close()
        speaker.close()
        if debouncer is not None:
            await debouncer.close()
        if jev is not None:
            await jev.__aexit__(None, None, None)
        if not started:
            print("Session did not start.", file=sys.stderr)
            emit({"type": "error", "text": "Session did not start."})


def main() -> None:
    args = parse_args()
    if args.list_devices:
        list_devices()
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
