import os
import argparse
import yaml
from dotenv import load_dotenv

from app.db.supabase_client import apply_migration


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

    args = parser.parse_args()

    if args.cmd == "check-config":
        check_config()
    elif args.cmd == "init-db":
        raise SystemExit(init_db())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
