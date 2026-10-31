-- Runtime settings editable from the web UI (M7.1). Empty / missing row = env fallback.
-- HACK: secrets stored as plaintext (single demo user, endpoints behind DEMO_TOKEN).
create table if not exists app_settings (
  key text primary key,
  value text not null,
  updated_at timestamptz default now()
);
