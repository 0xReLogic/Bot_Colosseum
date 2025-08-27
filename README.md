# Bot Colosseum

Bot Colosseum is a multi-bot debate scaffold for Telegram that enables automated debates between AI personas with a judge bot providing summaries and topic management.

## Features

- **Automated Debates**: Four distinct AI personas (Alpha-001, Beta-002, Gamma-003, Delta-004) engage in structured debates
- **Judge Bot**: Relogic-001 provides periodic summaries of debate sessions and manages topics
- **Round-Robin Discussion**: Personas take turns in a predetermined order
- **Topic Rotation**: Automatic daily topic changes at scheduled times
- **Database Integration**: PostgreSQL support for logging debate sessions, messages, and token usage
- **Admin-Only Access**: All debate controls restricted to Telegram group administrators

## Prerequisites

- Docker and Docker Compose
- Telegram supergroup with Topics enabled
- 5 Telegram bots created via BotFather:
  - 4 persona bots (Alpha-001, Beta-002, Gamma-003, Delta-004)
  - 1 judge bot (Relogic-001) - must be admin in the group
- Groq API key for persona responses
- Gemini API key for judge summaries
- Supabase PostgreSQL database connection

## Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` to set your configuration values:
   - `TELEGRAM_BOT_TOKENS`: Comma-separated list of 4 persona bot tokens
   - `TELEGRAM_JUDGE_TOKEN`: Token for the judge bot
   - `GROQ_API_KEY`: API key for Groq LLM service
   - `GEMINI_API_KEY`: API key for Google Gemini service
   - `DATABASE_URL`: Supabase PostgreSQL connection string

3. Configure personas in `config/personas.yaml`:
   - Each persona has a unique key, name, system prompt, and temperature setting
   - Personas: Alpha (philosopher), Beta (scientist), Gamma (politician), Delta (skeptic)

4. Configure models in `config/models.yaml`:
   - Maps each persona to a specific LLM model from Groq
   - Default models: llama-3.1-8b-instant, llama3-8b-8192, gemma2-9b-it, allam-2-7b

5. Configure debate topics in `config/topics.yaml`:
   - List of debate topics with categories, titles, descriptions, and tags

## Deployment

1. Build the Docker image:
   ```bash
   docker compose build
   ```

2. Apply database migrations (optional but recommended):
   ```bash
   docker compose --profile tools run --rm migrate
   ```

3. Run the bot:
   ```bash
   docker compose up -d bot
   ```

4. Check logs:
   ```bash
   docker compose logs -f bot
   ```

5. Stop the bot:
   ```bash
   docker compose down
   ```

## Telegram Setup

1. Add all 5 bots to your Telegram supergroup
2. Enable Topics in Group Settings
3. Make the judge bot (Relogic-001) an administrator in the group

## Commands (Admin-Only)

- `/start_debate [optional topic]` - Start a new debate in the current thread
- `/stop_debate` - Stop the current debate session
- `/next_topic` - Rotate to the next topic in `config/topics.yaml`
- `/summary` - Ask the judge to post an immediate summary
- `/enable_daily` - Schedule daily topic rotation at 09:00 (default timezone +08:00)
- `/disable_daily` - Stop daily topic rotation
- `/status` - Show the current topic and debate round
- `/usage` - Display token usage statistics for all LLM providers
- `/add_topic <title>` - Add a new debate topic
- `/list_topics` - List all configured debate topics
- `/gen_topics <count>` - Generate new debate topics using the judge bot

## How It Works

The system uses a debate orchestrator that manages the flow of conversation between the four persona bots. Each bot takes turns posting messages according to a configurable cadence (default: every 2 minutes). The judge bot periodically summarizes the discussion using Google Gemini and can trigger topic changes.

Key components:
- `app/main.py` - Entry point and configuration loader
- `app/debate/orchestrator.py` - Core debate logic and persona management
- `app/judge/gemini_client.py` - Judge bot implementation using Google Gemini
- `app/llm/groq_client.py` - LLM integration with Groq API
- `app/db/supabase_client.py` - Database operations and logging
- `app/telegram/handlers.py` - Telegram command handlers and routing

Database schema includes tables for personas, bots, topics, debate sessions, messages, and LLM usage tracking.

## Updating

To update the system after making changes to the codebase:

```bash
git pull
docker compose build
docker compose up -d bot
```

If database schema changes were made, re-run migrations:
```bash
docker compose --profile tools run --rm migrate
```

## Troubleshooting

- Missing tokens or keys: Check `docker compose logs -f bot` and `.env` file
- Judge cannot post summaries: Ensure judge bot is admin in the Telegram group
- Forum topic creation fails: Enable Topics in group settings and give admin rights
- Database not logging: Ensure `DATABASE_URL` is set and migrations have been applied
