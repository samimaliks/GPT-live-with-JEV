"""One page for the live call. The agent sends the calendar invite from the conversation.

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import asyncio
import importlib
import os
import threading
from typing import Any

import streamlit as st
from calendar_invite import EMAIL_RE
from dotenv import load_dotenv
from live_voice import EmailInbox


class CallBoard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.status = "Idle"
        self.user = ""
        self.agent = ""
        self.jev_lines: list[str] = []
        self.verdict: dict[str, Any] = {}
        self.error = ""
        self.need_email = False
        self.invite_done = False
        self.hangup = threading.Event()
        self.inbox = EmailInbox()
        self.thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "user": self.user,
                "agent": self.agent,
                "jev_lines": list(self.jev_lines),
                "verdict": dict(self.verdict),
                "error": self.error,
                "need_email": self.need_email,
                "invite_done": self.invite_done,
                "running": self.thread is not None and self.thread.is_alive(),
            }

    def on_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        with self._lock:
            if kind == "status":
                self.status = str(event.get("text", ""))
            elif kind == "transcript":
                self.user = str(event.get("user", ""))
                self.agent = str(event.get("agent", ""))
            elif kind == "jev":
                line = str(event.get("line", ""))
                if line and (not self.jev_lines or self.jev_lines[-1] != line):
                    self.jev_lines.append(line)
                    self.jev_lines = self.jev_lines[-12:]
                verdict = event.get("verdict")
                if isinstance(verdict, dict):
                    self.verdict = verdict
            elif kind == "need_email":
                self.need_email = True
            elif kind == "invite_sent":
                self.invite_done = True
                self.status = str(event.get("text", "Calendar invite sent."))
            elif kind == "error":
                self.error = str(event.get("text", ""))
                self.status = "Something went wrong"
            elif kind == "closed":
                self.status = str(event.get("text", "Call ended."))

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        with self._lock:
            self.status = "Starting"
            self.user = ""
            self.agent = ""
            self.jev_lines = []
            self.verdict = {}
            self.error = ""
            self.need_email = False
            self.invite_done = False
        self.hangup = threading.Event()
        self.inbox = EmailInbox()
        board = self

        def worker() -> None:
            import calendar_invite
            import live_voice

            importlib.reload(calendar_invite)
            importlib.reload(live_voice)
            args = argparse.Namespace(
                web_search=False,
                backend_model="gpt-5.6-luna",
                voice="marin",
                input_device=None,
                output_device=None,
                jev=True,
            )
            try:
                asyncio.run(
                    live_voice.run(args, sink=board.on_event, hangup=board.hangup, inbox=board.inbox)
                )
            except SystemExit as exc:
                board.on_event({"type": "error", "text": str(exc)})
            except Exception as exc:
                board.on_event({"type": "error", "text": str(exc)})
            finally:
                board.on_event({"type": "closed", "text": "Call ended."})

        self.thread = threading.Thread(target=worker, name="live-call", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.hangup.set()


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Personal agent", layout="centered")
    st.title("Personal agent")
    st.caption("Ask for existing invites, or ask to send one. The email box appears under this line when a send is requested.")

    if "board" not in st.session_state:
        st.session_state.board = CallBoard()
    board: CallBoard = st.session_state.board

    if not os.environ.get("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY is missing from .env. The call cannot start.")
    if not os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("TYPESAFE_API_KEY"):
        st.warning("No OpenRouter or TypeSafe key. The call still runs, without Jev scores.")

    @st.fragment(run_every=1)
    def live_panel() -> None:
        view = board.snapshot()
        left, right = st.columns(2)
        def begin() -> None:
            st.session_state.show_email_box = False
            board.start()

        with left:
            st.button(
                "Start call",
                type="primary",
                disabled=view["running"] or not os.environ.get("OPENAI_API_KEY"),
                on_click=begin,
            )
        with right:
            st.button("Hang up", disabled=not view["running"], on_click=board.stop)
        st.write(view["status"])
        if view["error"]:
            st.error(view["error"])
        st.subheader("You")
        st.write(view["user"] or "…")
        st.subheader("Rep")
        st.write(view["agent"] or "…")
        st.subheader("Jev")
        if view["jev_lines"]:
            st.code("\n".join(view["jev_lines"]))
        else:
            st.write("Scores appear here after someone speaks.")
        if view["need_email"] and not st.session_state.get("show_email_box"):
            st.session_state.show_email_box = True
            st.rerun()
        if view["invite_done"] and st.session_state.get("show_email_box"):
            st.session_state.show_email_box = False
            st.rerun()

    view = board.snapshot()
    if st.session_state.get("show_email_box") and view["running"] and not view["invite_done"]:
        with st.form("invite_email"):
            typed = st.text_input("Email for the calendar invite", placeholder="name@company.com")
            submitted = st.form_submit_button("Enter")
        if submitted:
            if EMAIL_RE.fullmatch(typed.strip()):
                board.inbox.submit(typed.strip())
                st.success(f"Sending the invite to {typed.strip()}.")
            else:
                st.error("Type a normal email address, then press Enter.")
    if view["invite_done"]:
        st.success(view["status"])

    live_panel()


main()
