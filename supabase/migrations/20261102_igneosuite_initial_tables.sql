-- Applied to Supabase project Octa_projects on 2026-11-02 (migration "igneosuite_initial_tables").
-- IgneoSuite tables. No uploaded data values are ever stored: only counts, settings and scores.

create table public."IgneoSuite_runs" (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  user_id uuid references auth.users(id) on delete set null,
  session_id text not null check (char_length(session_id) <= 64),
  app_version text check (char_length(app_version) <= 20),
  n_samples integer check (n_samples >= 0),
  n_variables integer check (n_variables >= 0),
  pct_missing real check (pct_missing between 0 and 100),
  n_complete integer check (n_complete >= 0),
  methods text[] check (cardinality(methods) <= 20),
  repetitions smallint check (repetitions between 1 and 50),
  scattered_frac real check (scattered_frac between 0 and 1),
  block_frac real check (block_frac between 0 and 1),
  block_variables text[] check (cardinality(block_variables) <= 200),
  recommended_method text check (char_length(recommended_method) <= 40),
  scores jsonb check (pg_column_size(scores) <= 65536),
  duration_s real check (duration_s >= 0)
);

create table public."IgneoSuite_events" (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id uuid references auth.users(id) on delete set null,
  session_id text not null check (char_length(session_id) <= 64),
  app_version text check (char_length(app_version) <= 20),
  event text not null check (event in ('load','diagnose','test','fill','export','cluster','about')),
  detail jsonb check (pg_column_size(detail) <= 8192)
);

create table public."IgneoSuite_feedback" (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  user_id uuid references auth.users(id) on delete set null,
  session_id text not null check (char_length(session_id) <= 64),
  app_version text check (char_length(app_version) <= 20),
  rating smallint check (rating between 1 and 5),
  message text check (char_length(message) <= 4000),
  contact_email text check (char_length(contact_email) <= 254)
);

create index "IgneoSuite_runs_created_at_idx" on public."IgneoSuite_runs" (created_at);
create index "IgneoSuite_runs_user_id_idx" on public."IgneoSuite_runs" (user_id);
create index "IgneoSuite_events_created_at_idx" on public."IgneoSuite_events" (created_at);
create index "IgneoSuite_events_user_id_idx" on public."IgneoSuite_events" (user_id);
create index "IgneoSuite_feedback_user_id_idx" on public."IgneoSuite_feedback" (user_id);

alter table public."IgneoSuite_runs" enable row level security;
alter table public."IgneoSuite_events" enable row level security;
alter table public."IgneoSuite_feedback" enable row level security;

create policy "IgneoSuite_runs insert" on public."IgneoSuite_runs" for insert to anon, authenticated
  with check (user_id is null or user_id = (select auth.uid()));
create policy "IgneoSuite_runs read own" on public."IgneoSuite_runs" for select to authenticated
  using (user_id = (select auth.uid()));
create policy "IgneoSuite_events insert" on public."IgneoSuite_events" for insert to anon, authenticated
  with check (user_id is null or user_id = (select auth.uid()));
create policy "IgneoSuite_events read own" on public."IgneoSuite_events" for select to authenticated
  using (user_id = (select auth.uid()));
create policy "IgneoSuite_feedback insert" on public."IgneoSuite_feedback" for insert to anon, authenticated
  with check (user_id is null or user_id = (select auth.uid()));
create policy "IgneoSuite_feedback read own" on public."IgneoSuite_feedback" for select to authenticated
  using (user_id = (select auth.uid()));

grant insert on public."IgneoSuite_runs", public."IgneoSuite_events", public."IgneoSuite_feedback" to anon, authenticated;
grant select on public."IgneoSuite_runs", public."IgneoSuite_events", public."IgneoSuite_feedback" to authenticated;
revoke update, delete, truncate on public."IgneoSuite_runs", public."IgneoSuite_events", public."IgneoSuite_feedback" from anon, authenticated;
