from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Dict, Optional

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message

from app.debate.orchestrator import DebateOrchestrator, DailyScheduler


@dataclass
class State:
    orchestrator: DebateOrchestrator
    scheduler: DailyScheduler
    judge_bot: Bot
    persona_bots: Dict[str, Bot]
    turn_order: List[str]
    topics: List[str]


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


def build_router(state: State) -> Router:
    router = Router(name="judge_router")

    @router.message(Command("start_debate"))
    async def start_debate(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return

        topic_title = None
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                topic_title = parts[1].strip()
        if not topic_title:
            topic_title = state.topics[0] if state.topics else "Debate"

        # Stop any existing sessions in this chat to avoid overlaps
        await state.orchestrator.stop_all_sessions_for_chat(message.chat.id)
        thread_id = getattr(message, "message_thread_id", None)
        await state.orchestrator.start_session(
            chat_id=message.chat.id,
            topic_title=topic_title,
            turn_order=state.turn_order,
            thread_id=thread_id,
        )
        await message.reply(f"Debat dimulai. Topik: {topic_title}")

    @router.message(Command("stop_debate"))
    async def stop_debate(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        thread_id = getattr(message, "message_thread_id", None)
        ok = await state.orchestrator.stop_session(message.chat.id, thread_id)
        await message.reply("Debat dihentikan." if ok else "Tidak ada sesi aktif.")

    @router.message(Command("next_topic"))
    async def next_topic(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        # Stop current sessions first, then advance topic by creating new forum topic
        await state.orchestrator.stop_all_sessions_for_chat(message.chat.id)
        # advance to next topic by creating new forum topic
        title = state.topics.pop(0) if state.topics else "Topik Baru"
        state.topics.append(title)
        thread_id = None
        try:
            topic = await state.judge_bot.create_forum_topic(chat_id=message.chat.id, name=title)
            thread_id = topic.message_thread_id
        except Exception as e:  # noqa: BLE001
            await message.reply(f"Gagal membuat topik forum baru: {e}. Memulai di thread saat ini.")
            thread_id = getattr(message, "message_thread_id", None)

        await state.orchestrator.start_session(
            chat_id=message.chat.id,
            topic_title=title,
            turn_order=state.turn_order,
            thread_id=thread_id,
        )
        await message.reply(f"Topik berikutnya dimulai: {title}")

    @router.message(Command("summary"))
    async def summary(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        thread_id = getattr(message, "message_thread_id", None)
        ok = await state.orchestrator.post_summary_now(message.chat.id, thread_id)
        if ok:
            await message.reply("Ringkasan juri diminta.")
        else:
            await message.reply("Tidak ada sesi atau juri non-aktif.")

    @router.message(Command("enable_daily"))
    async def enable_daily(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        # Use 09:00 local (+08:00) by default; can be overridden via env in runner when scheduler created
        state.scheduler.start(
            chat_id=message.chat.id,
            daily_time="09:00",
            topics=state.topics,
            turn_order=state.turn_order,
        )
        await message.reply("Penjadwalan harian diaktifkan (09:00).")

    @router.message(Command("disable_daily"))
    async def disable_daily(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        # cancel task if any
        if state.scheduler._task and not state.scheduler._task.done():  # noqa: SLF001
            state.scheduler._task.cancel()  # noqa: SLF001
            await asyncio.sleep(0)
            await message.reply("Penjadwalan harian dimatikan.")
        else:
            await message.reply("Tidak ada penjadwalan aktif.")

    @router.message(F.text == "/status")
    async def status(message: Message) -> None:
        thread_id = getattr(message, "message_thread_id", None)
        sess = state.orchestrator.get_session(message.chat.id, thread_id)
        if not sess:
            await message.reply("Tidak ada sesi aktif.")
            return
        await message.reply(
            f"Topik: {sess.topic_title}\nGiliran: {sess.turn_index}\nPeserta: {', '.join(state.turn_order)}"
        )

    return router
