-- Track token usage per generation
create table if not exists llm_usage (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references debate_sessions(id),
  chat_id bigint,
  thread_id bigint,
  provider text not null,             -- 'groq' | 'gemini'
  model_name text not null,
  role text,                          -- 'assistant' | 'system' | 'judge'
  prompt_tokens int,
  completion_tokens int,
  total_tokens int,
  meta jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create index if not exists llm_usage_created_at_idx on llm_usage(created_at);
create index if not exists llm_usage_chat_idx on llm_usage(chat_id);
