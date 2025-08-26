from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import contextlib
import os
from typing import Dict, List, Optional, Tuple

from aiogram import Bot

from app.llm.groq_client import GroqClient
from app.db.supabase_client import (
    create_debate_session,
    end_debate_session,
    insert_message,
)


@dataclasses.dataclass
class Persona:
    key: str
    name: str
    system_prompt: str
    model: str


@dataclasses.dataclass
class DebateSession:
    chat_id: int
    thread_id: Optional[int]
    topic_title: str
    personas_order: List[str]  # keys
    active: bool = True
    turn_index: int = 0
    history: List[Tuple[str, str]] = dataclasses.field(default_factory=list)  # (speaker_key, text)
    judge_summary: Optional[str] = None
    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    session_db_id: Optional[str] = None


class DebateOrchestrator:
    def __init__(
        self,
        groq: GroqClient,
        persona_map: Dict[str, Persona],
        persona_bots: Dict[str, Bot],
        judge_bot: Optional[Bot] = None,
        cadence_seconds: int = 120,
        max_tokens: int = 120,
        context_turns: int = 4,
    ) -> None:
        self.groq = groq
        self.persona_map = persona_map
        self.persona_bots = persona_bots
        self.judge_bot = judge_bot
        self.cadence_seconds = cadence_seconds
        self.max_tokens = max_tokens
        self.context_turns = context_turns

        self.sessions: Dict[Tuple[int, Optional[int]], DebateSession] = {}
        self._tasks: Dict[Tuple[int, Optional[int]], asyncio.Task] = {}

        # Judge summary cadence (turn groups)
        self.judge_summary_every_turns = int(os.getenv("JUDGE_SUMMARY_EVERY_TURNS", "2"))
        self.judge_summary_max_tokens = int(os.getenv("JUDGE_SUMMARY_MAX_TOKENS", "120"))

    def _session_key(self, chat_id: int, thread_id: Optional[int]) -> Tuple[int, Optional[int]]:
        return (chat_id, thread_id)

    def get_session(self, chat_id: int, thread_id: Optional[int]) -> Optional[DebateSession]:
        return self.sessions.get(self._session_key(chat_id, thread_id))

    async def start_session(
        self,
        chat_id: int,
        topic_title: str,
        turn_order: List[str],
        thread_id: Optional[int] = None,
    ) -> DebateSession:
        key = self._session_key(chat_id, thread_id)
        if key in self.sessions and self.sessions[key].active:
            return self.sessions[key]

        session = DebateSession(
            chat_id=chat_id,
            thread_id=thread_id,
            topic_title=topic_title,
            personas_order=turn_order,
            active=True,
        )
        # Create DB session (non-blocking) if DATABASE_URL configured
        try:
            session.session_db_id = await asyncio.to_thread(create_debate_session, chat_id, topic_title)
        except Exception:
            session.session_db_id = None
        self.sessions[key] = session

        # spawn background loop
        task = asyncio.create_task(self._debate_loop(session))
        self._tasks[key] = task
        return session

    async def stop_session(self, chat_id: int, thread_id: Optional[int]) -> bool:
        key = self._session_key(chat_id, thread_id)
        session = self.sessions.get(key)
        if not session:
            return False
        session.active = False
        task = self._tasks.get(key)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # End DB session if exists
        if session.session_db_id:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(end_debate_session, session.session_db_id)
        return True

    async def stop_all_sessions_for_chat(self, chat_id: int) -> int:
        """Stop every active session in a chat (all threads). Returns count stopped."""
        keys = [k for k in list(self.sessions.keys()) if k[0] == chat_id]
        count = 0
        for key in keys:
            session = self.sessions.get(key)
            if session and session.active:
                session.active = False
                task = self._tasks.get(key)
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                # End DB session if exists
                if session.session_db_id:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(end_debate_session, session.session_db_id)
                count += 1
        return count

    async def _debate_loop(self, session: DebateSession) -> None:
        try:
            while session.active:
                await asyncio.sleep(self.cadence_seconds)
                try:
                    await self._post_next_turn(session)
                except Exception as e:  # noqa: BLE001
                    # swallow errors to keep loop alive
                    print(f"[debate_loop] error: {e}")
        except asyncio.CancelledError:
            return

    def _build_messages(self, session: DebateSession, speaker: Persona) -> List[dict]:
        # Build Chat Completions style messages
        sys = (
            speaker.system_prompt
            + "\nBahasa: Indonesia."
            + "\nInstruksi penting: jangan menyalin atau menulis label/nama persona (mis. 'Alpha-001:', 'Beta-002:', 'Gamma-003:', 'Delta-004:') atau frasa 'Ringkasan Juri'. Mulai langsung dengan bullet poin, tanpa heading/prefiks nama."
            + "\nGaya: ringkas, 3-5 bullet poin; kalimat pendek."
            + "\nJika ada ringkasan juri di konteks, gunakan hanya sebagai rujukan; jangan tulis frasa 'Ringkasan Juri' di jawaban."
            + f"\nTopik: {session.topic_title}\n"
        )
        messages: List[dict] = [{"role": "system", "content": sys}]

        # Add last context_turns from history as alternating user/assistant snippets
        # Simplify: add combined recent context as a user message
        recent = session.history[-self.context_turns :]
        if recent:
            ctx_text = []
            for spk_key, text in recent:
                name = self.persona_map.get(spk_key).name if spk_key in self.persona_map else spk_key
                ctx_text.append(f"{name}: {text}")
            messages.append({"role": "user", "content": "\n".join(ctx_text)})
        if session.judge_summary:
            messages.append({"role": "user", "content": f"Ringkasan Juri: {session.judge_summary}"})
        return messages

    async def _post_next_turn(self, session: DebateSession) -> None:
        async with session.lock:
            if not session.active:
                return
            speaker_key = session.personas_order[session.turn_index % len(session.personas_order)]
            speaker = self.persona_map[speaker_key]
            bot = self.persona_bots.get(speaker_key)
            if not bot:
                # skip if bot missing
                session.turn_index += 1
                return

            messages = self._build_messages(session, speaker)
            try:
                stop_list = [f"{p.name}:" for p in self.persona_map.values()] + [
                    "Ringkasan Juri:",
                    "Ringkasan Juri",
                ]
                text = self.groq.chat(
                    model=speaker.model,
                    messages=messages,
                    temperature=0.6,
                    max_tokens=self.max_tokens,
                    stop=stop_list,
                )
            except Exception as e:  # noqa: BLE001
                text = f"(gagal generate: {e})"

            # send to chat (thread if exists)
            try:
                msg = await bot.send_message(
                    chat_id=session.chat_id,
                    text=text,
                    message_thread_id=session.thread_id,
                    disable_notification=True,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[send_message] error: {e}")
                msg = None

            session.history.append((speaker_key, text))
            session.turn_index += 1

            # log to DB if configured
            if session.session_db_id:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        insert_message,
                        session.session_db_id,
                        text,
                        getattr(msg, "message_id", None) if msg else None,
                        "assistant",
                    )

            # judge summary cadence
            if (
                self.judge_bot
                and self.judge_summary_every_turns > 0
                and (session.turn_index % (self.judge_summary_every_turns * len(session.personas_order)) == 0)
            ):
                await self._post_judge_summary(session)

    async def _post_judge_summary(self, session: DebateSession) -> None:
        # Lazy import to avoid hard dep if not used
        try:
            from app.judge.gemini_client import GeminiJudge
        except Exception:
            return

        judge = GeminiJudge()
        recent_texts = [t for _, t in session.history[-(self.context_turns * len(session.personas_order)) :]]
        try:
            summary = await judge.summarize(recent_texts, max_tokens=self.judge_summary_max_tokens)
        except Exception as e:  # noqa: BLE001
            summary = f"(Ringkasan juri gagal: {e})"
        session.judge_summary = summary

        if self.judge_bot:
            try:
                msg = await self.judge_bot.send_message(
                    chat_id=session.chat_id,
                    text=f"[Ringkasan Juri]\n{summary}",
                    message_thread_id=session.thread_id,
                    disable_notification=True,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[judge_send] error: {e}")
                msg = None

            # log judge summary to DB as system role
            if session.session_db_id:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        insert_message,
                        session.session_db_id,
                        f"[Ringkasan Juri]\n{summary}",
                        getattr(msg, "message_id", None) if msg else None,
                        "system",
                    )

    async def post_summary_now(self, chat_id: int, thread_id: Optional[int]) -> bool:
        """Public method to request a judge summary immediately for a session."""
        key = self._session_key(chat_id, thread_id)
        session = self.sessions.get(key)
        if not session or not self.judge_bot:
            return False
        await self._post_judge_summary(session)
        return True


class DailyScheduler:
    def __init__(self, judge_bot: Bot, orchestrator: DebateOrchestrator, tz_offset_minutes: int = 480) -> None:
        self.judge_bot = judge_bot
        self.orchestrator = orchestrator
        self.tz_offset_minutes = tz_offset_minutes
        self._task: Optional[asyncio.Task] = None
        self._topics: List[str] = []
        self._topic_idx: int = 0

    def start(self, chat_id: int, daily_time: str, topics: List[str], turn_order: List[str]) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._topics = topics or []
        self._topic_idx = 0
        self._task = asyncio.create_task(self._run(chat_id, daily_time, turn_order))

    async def _run(self, chat_id: int, daily_time: str, turn_order: List[str]) -> None:
        while True:
            delay = self._seconds_until(daily_time)
            await asyncio.sleep(delay)
            # Attempt to create forum topic (needs admin rights)
            thread_id = None
            try:
                # Determine current topic title
                topic_title = self._topics[self._topic_idx % max(1, len(self._topics))] if self._topics else "Debate Harian"
                self._topic_idx += 1
                topic = await self.judge_bot.create_forum_topic(chat_id=chat_id, name=topic_title)
                thread_id = topic.message_thread_id
                await self.judge_bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=f"Topik hari ini: <b>{topic_title}</b>",
                )
            except Exception as e:  # noqa: BLE001
                print(f"[create_forum_topic] error: {e}")

            await self.orchestrator.start_session(chat_id=chat_id, topic_title=topic_title, turn_order=turn_order, thread_id=thread_id)

    def _seconds_until(self, daily_time: str) -> int:
        # daily_time format: HH:MM
        hh, mm = [int(x) for x in daily_time.split(":", 1)]
        offset = dt.timedelta(minutes=self.tz_offset_minutes)
        now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
        now_local = now_utc + offset
        target_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target_local <= now_local:
            target_local = target_local + dt.timedelta(days=1)
        delta = (target_local - now_local).total_seconds()
        return int(delta)
