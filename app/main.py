import os
import argparse
import asyncio
import yaml
from dotenv import load_dotenv

from app.db.supabase_client import apply_migration
from app.llm.groq_client import GroqClient
from app.debate.orchestrator import DebateOrchestrator, Persona, DailyScheduler
from app.telegram.handlers import build_router, State
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT_DIR)


def read_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_config():
    groq_set = bool(os.getenv("GROQ_API_KEY"))
    db_url = os.getenv("DATABASE_URL")
    tokens_raw = os.getenv("TELEGRAM_BOT_TOKENS", "")
    token_count = len([t for t in tokens_raw.split(",") if t.strip()])

    personas_cfg = read_yaml(os.path.join(PROJECT_ROOT, "config", "personas.yaml"))
    models_cfg = read_yaml(os.path.join(PROJECT_ROOT, "config", "models.yaml"))

    personas = [p.get("key") for p in personas_cfg.get("personas", [])]
    model_map = models_cfg.get("models", {})

    print("== Config Check ==")
    print(f"GROQ_API_KEY: {'set' if groq_set else 'missing'}")
    print(f"DATABASE_URL: {'set' if db_url else 'missing'}")
    print(f"TELEGRAM_BOT_TOKENS: {token_count} provided")

    missing_models = [p for p in personas if p not in model_map]
    if missing_models:
        print("Model mapping missing for personas:", ", ".join(missing_models))
    else:
        print("Model mapping complete:")
        for p in personas:
            print(f"  - {p}: {model_map[p]}")


def init_db() -> int:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is missing in environment.")
        return 1

    migration_path = os.path.join(PROJECT_ROOT, "migrations", "001_init.sql")
    try:
        apply_migration(db_url, migration_path)
        print("Database migration applied.")
        return 0
    except Exception as e:
        print("Migration failed:", e)
        return 2


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(prog="bot-colosseum", description="Multi-bot debate scaffold")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("check-config", help="Validate environment and configs")
    sub.add_parser("init-db", help="Apply database migrations")
    sub.add_parser("run", help="Start judge and debate orchestrator (Telegram bots)")

    args = parser.parse_args()

    if args.cmd == "check-config":
        check_config()
    elif args.cmd == "init-db":
        raise SystemExit(init_db())
    elif args.cmd == "run":
        asyncio.run(run())
    else:
        parser.print_help()


async def run() -> None:
    # Load configs
    personas_cfg = read_yaml(os.path.join(PROJECT_ROOT, "config", "personas.yaml"))
    models_cfg = read_yaml(os.path.join(PROJECT_ROOT, "config", "models.yaml"))
    topics_cfg = read_yaml(os.path.join(PROJECT_ROOT, "config", "topics.yaml"))

    persona_defs = personas_cfg.get("personas", [])
    model_map = models_cfg.get("models", {})
    topics = [t.get("title") for t in topics_cfg.get("topics", []) if t.get("title")]

    # Build persona objects and turn order
    personas: list[Persona] = []
    for p in persona_defs:
        key = p.get("key")
        name = p.get("name")
        sys_prompt = p.get("system_prompt", "")
        model = model_map.get(key)
        if not all([key, name, sys_prompt, model]):
            continue
        personas.append(Persona(key=key, name=name, system_prompt=sys_prompt, model=model))

    if not personas:
        raise RuntimeError("No personas configured")

    turn_order = [p.key for p in personas]

    # Tokens and clients
    tokens_raw = os.getenv("TELEGRAM_BOT_TOKENS", "")
    tokens = [t.strip() for t in tokens_raw.split(",") if t.strip()]
    if len(tokens) < len(turn_order):
        raise RuntimeError(f"TELEGRAM_BOT_TOKENS requires {len(turn_order)} tokens, got {len(tokens)}")

    judge_token = os.getenv("TELEGRAM_JUDGE_TOKEN")
    if not judge_token:
        raise RuntimeError("TELEGRAM_JUDGE_TOKEN is not set")

    # Create bots
    judge_bot = Bot(token=judge_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    persona_bots = {}
    for i, key in enumerate(turn_order):
        persona_bots[key] = Bot(token=tokens[i], default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Orchestrator settings
    cadence_seconds = int(os.getenv("DEBATE_CADENCE_SECONDS", "120"))
    max_tokens = int(os.getenv("BOT_MESSAGE_MAX_TOKENS", "120"))
    context_turns = int(os.getenv("BOT_CONTEXT_TURNS", "4"))

    groq = GroqClient()
    persona_map = {p.key: p for p in personas}
    orchestrator = DebateOrchestrator(
        groq=groq,
        persona_map=persona_map,
        persona_bots=persona_bots,
        judge_bot=judge_bot,
        cadence_seconds=cadence_seconds,
        max_tokens=max_tokens,
        context_turns=context_turns,
    )

    # Scheduler
    tz_offset_minutes = int(os.getenv("TZ_OFFSET_MINUTES", "480"))  # +08:00 default
    scheduler = DailyScheduler(judge_bot=judge_bot, orchestrator=orchestrator, tz_offset_minutes=tz_offset_minutes)

    # Telegram dispatcher and routes
    state = State(
        orchestrator=orchestrator,
        scheduler=scheduler,
        judge_bot=judge_bot,
        persona_bots=persona_bots,
        turn_order=turn_order,
        topics=topics,
    )
    dp = Dispatcher()
    dp.include_router(build_router(state))

    print("Judge bot polling started. Use /start_debate in your supergroup.")
    await dp.start_polling(judge_bot)


if __name__ == "__main__":
    main()
