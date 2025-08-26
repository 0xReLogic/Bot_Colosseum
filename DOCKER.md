# Bot Colosseum (Docker Quickstart)

Multi-bot debate scaffold for Telegram with round-robin personas and a judge.

## Prerequisites
- Docker + Docker Compose plugin
- A Telegram supergroup with Topics enabled
- 5 bots created in BotFather:
  - 4 persona bots (Alpha-001, Beta-002, Gamma-003, Delta-004)
  - 1 judge bot (Relogic-001) — must be admin in the group

## 1) Configure environment
Copy the example file and fill in values.

```powershell
Copy-Item .env.example .env
# Edit .env and set TELEGRAM tokens, GROQ_API_KEY, GEMINI_API_KEY, DATABASE_URL (Supabase)
```

Notes
- DATABASE_URL (Supabase) example: `postgresql://postgres:<PASSWORD>@db.<PROJECT>.supabase.co:5432/postgres`
- Defaults match the agreed setup: cadence 120s, max_tokens 120, context_turns 4, judge summary every 2 rounds, daily 09:00 +08:00.

## 2) Build the image
```powershell
docker compose build
```

## 3) Apply database migration (optional but recommended)
This creates tables and extensions (pgcrypto, vector). Safe to run multiple times.

```powershell
docker compose --profile tools run --rm migrate
```

If `vector` extension fails, enable “pgvector” in Supabase Dashboard or run this in SQL editor:
```sql
create extension if not exists pgcrypto;
create extension if not exists vector;
```
Then re-run the migration command above.

## 4) Run the bot
```powershell
docker compose up -d bot
```

Check logs:
```powershell
docker compose logs -f bot
```

Stop:
```powershell
docker compose down
```

## Telegram setup checklist
- Add all 5 bots to your supergroup.
- Enable Topics in Group Settings.
- Make the judge bot (Relogic-001) an admin.

## Commands (admin-only)
- `/start_debate [optional topic]` — start a new debate in current thread.
- `/stop_debate` — stop current debate session.
- `/next_topic` — rotate to next topic in `config/topics.yaml` (tries to create a new forum topic).
- `/summary` — ask judge to post an immediate summary.
- `/enable_daily` — schedule daily rotation at 09:00 (+08:00 default).
- `/disable_daily` — stop daily rotation.
- `/status` — show current topic and round.

## How it works
- Runtime: `python -m app.main run`
- Orchestrator: `app/debate/orchestrator.py` (round-robin posts, rolling context, judge summaries)
- Judge (Gemini): `app/judge/gemini_client.py`
- Telegram router: `app/telegram/handlers.py`
- Migration: `migrations/001_init.sql`
- Optional DB logging (Supabase): `app/db/supabase_client.py` — logs sessions/messages when `DATABASE_URL` is set.

## Updating
```powershell
git pull
docker compose build
# (optional) re-run migration if schema changed
# docker compose --profile tools run --rm migrate

docker compose up -d bot
```

## Troubleshooting
- Missing tokens or keys → check `docker compose logs -f bot` and `.env`.
- Judge cannot post summaries → ensure judge is admin in the group.
- Forum topic creation fails → enable Topics and give admin rights, or the bot will fallback to current thread.
- DB not logging → ensure `DATABASE_URL` is set; run migrations; check Supabase network/firewall.
