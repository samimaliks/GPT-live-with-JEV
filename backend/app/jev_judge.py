"""Score a live personal-assistant call. Jev returns probabilities; it does not speak."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_MODEL = "jev-1.13"
TYPESAFE_MODEL = "jev-latest"
QUIET_SECONDS = 0.4

QUESTIONS = {
    "caller_intent": Choice(
        instructions="What is the user doing in this moment with their personal assistant?",
        criteria={
            "calendar": "They are asking about their calendar or a meeting.",
            "weather": "They are asking about the weather.",
            "question": "They are asking a current or general question.",
            "meeting": "They want to book a meeting or send an invite.",
            "goodbye": "They are ending the call.",
            "unclear": "There is not enough speech yet to tell.",
        },
    ),
    "invented_fact": Noul(
        instructions=(
            "Did the assistant state a calendar event, weather reading, or web result "
            "that the system had not already given it?"
        ),
    ),
    "long_pitch": Noul(
        instructions="Is the assistant giving a long monologue instead of a short conversational turn?",
    ),
    "should_close": Noul(
        instructions="Has the user said goodbye?",
    ),
    "agreed_meeting": Noul(
        instructions="Has the user asked to book a meeting or send a calendar invite?",
    ),
}


def utterance_ended(fragment: str) -> bool:
    return fragment.rstrip().endswith((".", "!", "?"))


def format_verdict(verdict: dict[str, Any]) -> str:
    return (
        f"[jev] intent={verdict['intent']} {verdict['intent_p']:.2f} "
        f"invented_fact={verdict['invented_fact']:.2f} "
        f"long_pitch={verdict['long_pitch']:.2f} "
        f"should_close={verdict['should_close']:.2f} "
        f"agreed_meeting={verdict['agreed_meeting']:.2f}"
    )


class JevJudge:
    def __init__(self) -> None:
        self._client: AsyncTypeSafeClient | None = None
        self._model = TYPESAFE_MODEL
        self._last_key: tuple[str, str, bool] | None = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def __aenter__(self) -> JevJudge:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        typesafe_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if openrouter_key:
            self._model = OPENROUTER_MODEL
            self._client = AsyncTypeSafeClient(
                api_key=openrouter_key,
                base_url=OPENROUTER_BASE_URL,
                model=OPENROUTER_MODEL,
            )
            print("Jev is using your OpenRouter key.")
        elif typesafe_key:
            self._client = AsyncTypeSafeClient(api_key=typesafe_key, model=TYPESAFE_MODEL)
        else:
            print("Jev skipped: put your OpenRouter key in .env as OPENROUTER_API_KEY.")
            return self
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)

    async def judge(
        self,
        *,
        brief: str,
        user: str,
        agent: str,
        email_seen: bool,
    ) -> dict[str, Any] | None:
        if self._client is None:
            return None
        user = user[-2000:]
        agent = agent[-2000:]
        key = (user, agent, email_seen)
        if key == self._last_key or (not user.strip() and not agent.strip()):
            return None
        response = await self._client.system_one(
            {
                "brief": brief,
                "user": user,
                "agent": agent,
                "email_seen": email_seen,
            },
            QUESTIONS,
            model=self._model,
        )
        self._last_key = key
        intent = response.choices["caller_intent"]
        return {
            "intent": intent.choice,
            "intent_p": intent.probabilities.get(intent.choice, 0.0),
            "invented_fact": response.nouls["invented_fact"].noul,
            "long_pitch": response.nouls["long_pitch"].noul,
            "should_close": response.nouls["should_close"].noul,
            "agreed_meeting": response.nouls["agreed_meeting"].noul,
        }


class TranscriptDebouncer:
    """Run after punctuation, or after a short quiet period if the text changed."""

    def __init__(self, quiet_s: float = QUIET_SECONDS) -> None:
        self.quiet_s = quiet_s
        self._task: asyncio.Task[None] | None = None
        self._generation = 0

    def push(self, text_ended: bool, run: Callable[[], Awaitable[None]]) -> None:
        self._generation += 1
        generation = self._generation
        if self._task is not None and not self._task.done():
            self._task.cancel()
        delay = 0.05 if text_ended else self.quiet_s

        async def wait() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if generation != self._generation:
                return
            await run()

        self._task = asyncio.create_task(wait())

    async def close(self) -> None:
        self._generation += 1
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
