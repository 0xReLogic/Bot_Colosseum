from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Dict, Optional

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message

from app.debate.orchestrator import DebateOrchestrator, DailyScheduler
from app.db.supabase_client import get_usage_summary, ensure_topic


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

    @router.message(Command("tick"))
    async def tick(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        thread_id = getattr(message, "message_thread_id", None)
        sess = state.orchestrator.get_session(message.chat.id, thread_id)
        if not sess or not sess.active:
            await message.reply("Tidak ada sesi aktif di thread ini.")
            return
        # Force an immediate next turn
        try:
            await state.orchestrator._post_next_turn(sess)  # noqa: SLF001
            await message.reply("1 giliran dipaksa berjalan.")
        except Exception as e:  # noqa: BLE001
            await message.reply(f"Gagal mengeksekusi tick: {e}")

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

    @router.message(Command("usage"))
    async def usage(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        # parse hours
        hours = 24
        if message.text:
            parts = message.text.split()
            if len(parts) >= 2:
                try:
                    hours = max(1, int(parts[1]))
                except Exception:
                    hours = 24
        thread_id = getattr(message, "message_thread_id", None)
        rows = await asyncio.to_thread(get_usage_summary, message.chat.id, hours, thread_id)
        if not rows:
            await message.reply("Belum ada data pemakaian atau DB non-aktif.")
            return
        lines = [f"Pemakaian {hours} jam terakhir:" ]
        total = 0
        for r in rows:
            lines.append(
                f"• {r['provider']} / {r['model_name']}: prompt={r['prompt_tokens']}, completion={r['completion_tokens']}, total={r['total_tokens']}"
            )
            total += int(r.get('total_tokens', 0))
        lines.append(f"Total tokens: {total}")
        await message.reply("\n".join(lines))

    @router.message(Command("add_topic"))
    async def add_topic(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        title = None
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                title = parts[1].strip()
        if not title:
            await message.reply("Gunakan: /add_topic <judul_topik>")
            return
        state.topics.append(title)
        # persist to DB if available
        ok = await asyncio.to_thread(ensure_topic, title)
        suffix = " (disimpan ke DB)" if ok else ""
        await message.reply(f"Topik ditambahkan (#{len(state.topics)}): {title}{suffix}")

    @router.message(Command("list_topics"))
    async def list_topics(message: Message) -> None:
        if not state.topics:
            await message.reply("Daftar topik kosong.")
            return
        preview = "\n".join([f"{i+1}. {t}" for i, t in enumerate(state.topics[:20])])
        extra = "" if len(state.topics) <= 20 else f"\n(+{len(state.topics)-20} lainnya)"
        await message.reply(f"Total topik: {len(state.topics)}\n{preview}{extra}")

    @router.message(Command("gen_topics"))
    async def gen_topics(message: Message) -> None:
        if not message.from_user:
            return
        if not await _is_admin(state.judge_bot, message.chat.id, message.from_user.id):
            await message.reply("Perintah ini khusus admin.")
            return
        # parse: /gen_topics [keyword] [count]
        keyword = None
        count = 10
        if message.text:
            parts = message.text.split(maxsplit=2)
            if len(parts) >= 2:
                if parts[1].isdigit():
                    count = max(1, min(50, int(parts[1])))
                else:
                    keyword = parts[1].strip()
            if len(parts) == 3:
                try:
                    count = max(1, min(50, int(parts[2])))
                except Exception:
                    pass
        try:
            from app.judge.gemini_client import GeminiJudge
            gj = GeminiJudge()
            topics = await gj.generate_topics(keyword=keyword, count=count)
        except Exception as e:  # noqa: BLE001
            await message.reply(f"Gagal membuat topik via Gemini: {e}")
            return
        state.topics.extend(topics)
        # persist each to DB (best-effort)
        await asyncio.gather(*[asyncio.to_thread(ensure_topic, t) for t in topics])
        preview = "\n".join([f"- {t}" for t in topics])
        await message.reply(f"Ditambahkan {len(topics)} topik baru:\n{preview}")

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
