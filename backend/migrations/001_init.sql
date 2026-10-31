create extension if not exists vector;

create table if not exists users (
  id text primary key default gen_random_uuid()::text,
  name text not null default '',
  email text,
  slack_user_id text,
  telegram_chat_id text,
  created_at timestamptz not null default now()
);

create table if not exists experts (
  id text primary key default gen_random_uuid()::text,
  name text not null,
  role text,
  topics text[] not null default '{}',
  channel text not null default 'slack',
  email text,
  slack_user_id text,
  telegram_chat_id text,
  created_at timestamptz not null default now()
);

create table if not exists meetings (
  id text primary key default gen_random_uuid()::text,
  owner_id text references users(id) on delete set null,
  title text not null default '',
  platform text,
  meeting_url text,
  recall_bot_id text,
  mode text not null default 'notes',
  status text not null default 'scheduled',
  started_at timestamptz,
  ended_at timestamptz,
  summary text not null default '',
  decisions jsonb not null default '[]'::jsonb,
  action_items jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists meetings_recall_bot_id_idx on meetings(recall_bot_id);

create table if not exists utterances (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  speaker text not null default '',
  text text not null,
  ts_start real not null default 0,
  ts_end real,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  unique (meeting_id, speaker, ts_start)
);

create table if not exists kb_docs (
  id text primary key default gen_random_uuid()::text,
  title text not null,
  source text,
  version integer not null default 1,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists kb_chunks (
  id text primary key default gen_random_uuid()::text,
  doc_id text not null references kb_docs(id) on delete cascade,
  text text not null,
  embedding vector(1536),
  version integer not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists facts (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  speaker text,
  text text not null,
  kind text,
  embedding vector(1536),
  created_at timestamptz not null default now()
);

create table if not exists kb_update_proposals (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  doc_id text references kb_docs(id) on delete set null,
  chunk_id text references kb_chunks(id) on delete set null,
  old_text text,
  new_text text,
  speaker text,
  ts real,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);

create table if not exists fact_checks (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  utterance_id text references utterances(id) on delete set null,
  claim text not null,
  verdict text not null,
  kb_chunk_id text references kb_chunks(id) on delete set null,
  proposal_id text references kb_update_proposals(id) on delete set null,
  confidence real,
  correction text,
  posted boolean not null default false,
  ts real,
  created_at timestamptz not null default now()
);

create table if not exists briefs (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  text text not null default '',
  open_questions text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists escalations (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  expert_id text references experts(id) on delete set null,
  channel text not null default 'slack',
  question text not null,
  asked_by text,
  ts real,
  external_msg_id text,
  external_channel_id text,
  answer text,
  status text not null default 'waiting',
  asked_at timestamptz not null default now(),
  answered_at timestamptz,
  answered_ts real,
  created_at timestamptz not null default now()
);
create index if not exists escalations_status_idx on escalations(status);

create table if not exists chat_messages (
  id text primary key default gen_random_uuid()::text,
  user_id text references users(id) on delete cascade,
  role text not null,
  text text not null,
  citations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists agent_said (
  id text primary key default gen_random_uuid()::text,
  meeting_id text not null references meetings(id) on delete cascade,
  text text not null,
  ts real,
  in_reply_to text,
  created_at timestamptz not null default now()
);

create index if not exists kb_chunks_embedding_idx on kb_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists facts_embedding_idx on facts using hnsw (embedding vector_cosine_ops);
create index if not exists utterances_meeting_idx on utterances(meeting_id, ts_start);
