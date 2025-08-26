-- Initial schema for Bot Colosseum
create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists personas (
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  system_prompt text not null,
  style jsonb default '{}'::jsonb
);

create table if not exists bots (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  telegram_token text not null,
  persona_id uuid references personas(id),
  model_name text not null,
  active boolean default true
);

create table if not exists topics (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  tags text[]
);

create table if not exists debate_sessions (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid references topics(id),
  chat_id bigint not null,
  status text check (status in ('active','ended')) default 'active',
  round_index int default 0,
  max_rounds int default 3,
  turn_order uuid[] not null,
  started_at timestamptz default now(),
  ended_at timestamptz
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references debate_sessions(id),
  bot_id uuid references bots(id),
  role text check (role in ('system','user','assistant')) default 'assistant',
  content text not null,
  telegram_msg_id bigint,
  created_at timestamptz default now()
);

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid references personas(id),
  topic_id uuid references topics(id),
  title text,
  url text,
  text text not null,
  chunk_id text
);

create table if not exists vectors (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id) on delete cascade,
  embedding vector(384),
  metadata jsonb default '{}'::jsonb
);

create index if not exists vectors_embedding_idx on vectors using ivfflat (embedding vector_cosine_ops) with (lists = 100);
