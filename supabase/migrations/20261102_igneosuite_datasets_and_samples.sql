-- Applied to Supabase project Octa_projects on 2026-11-02 (migration "igneosuite_datasets_and_samples").
-- Author submissions: one row per dataset, one row per sample (with location and age).

create table public."IgneoSuite_datasets" (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  user_id uuid references auth.users(id) on delete set null,
  session_id text check (char_length(session_id) <= 64),
  app_version text check (char_length(app_version) <= 20),
  author_name text not null check (char_length(author_name) between 2 and 200),
  author_email text not null check (char_length(author_email) <= 254 and author_email like '%_@_%'),
  affiliation text check (char_length(affiliation) <= 300),
  title text not null check (char_length(title) between 3 and 300),
  reference text check (char_length(reference) <= 1000),
  description text check (char_length(description) <= 4000),
  licence text not null default 'CC-BY-4.0' check (licence in ('CC-BY-4.0','CC0-1.0','CC-BY-NC-4.0','restricted')),
  consent boolean not null check (consent),
  status text not null default 'submitted' check (status in ('submitted','approved','rejected')),
  n_samples integer check (n_samples between 0 and 200000),
  n_variables integer check (n_variables between 0 and 500),
  variables text[] check (cardinality(variables) <= 500),
  estimation_method text check (char_length(estimation_method) <= 40),
  error_band real check (error_band between 0 and 1)
);

create table public."IgneoSuite_samples" (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  dataset_id uuid not null references public."IgneoSuite_datasets"(id) on delete cascade,
  row_number integer not null check (row_number >= 1),
  sample_id text check (char_length(sample_id) <= 200),
  latitude double precision check (latitude between -90 and 90),
  longitude double precision check (longitude between -180 and 180),
  age_ma double precision check (age_ma between 0 and 4600),
  measured jsonb not null default '{}'::jsonb check (jsonb_typeof(measured) = 'object' and pg_column_size(measured) <= 32768),
  estimated jsonb check (estimated is null or (jsonb_typeof(estimated) = 'object' and pg_column_size(estimated) <= 32768)),
  estimate_error jsonb check (estimate_error is null or (jsonb_typeof(estimate_error) = 'object' and pg_column_size(estimate_error) <= 32768)),
  unique (dataset_id, row_number)
);
comment on column public."IgneoSuite_samples".latitude is 'Decimal degrees, WGS84, north positive';
comment on column public."IgneoSuite_samples".longitude is 'Decimal degrees, WGS84, east positive';
comment on column public."IgneoSuite_samples".age_ma is 'Age in Ma (million years)';

create index "IgneoSuite_samples_dataset_idx" on public."IgneoSuite_samples" (dataset_id);
create index "IgneoSuite_datasets_user_idx" on public."IgneoSuite_datasets" (user_id);
create index "IgneoSuite_datasets_status_idx" on public."IgneoSuite_datasets" (status);

create view public."IgneoSuite_values" with (security_invoker = true) as
select s.dataset_id, s.id as sample_row_id, s.sample_id, s.latitude, s.longitude, s.age_ma,
       v.key as variable,
       (s.measured ->> v.key)::double precision as measured,
       (s.estimated ->> v.key)::double precision as estimated,
       (s.estimate_error ->> v.key)::double precision as estimate_error
from public."IgneoSuite_samples" s
cross join lateral (
  select jsonb_object_keys(s.measured) as key
  union
  select jsonb_object_keys(coalesce(s.estimated, '{}'::jsonb))
) v;

create or replace function public."IgneoSuite_check_sample_window"()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if not exists (
    select 1 from public."IgneoSuite_datasets" d
    where d.id = new.dataset_id and d.status = 'submitted' and d.created_at > now() - interval '2 hours'
  ) then
    raise exception 'Samples can only be added to a newly submitted dataset';
  end if;
  return new;
end $$;
revoke execute on function public."IgneoSuite_check_sample_window"() from public, anon, authenticated;
create trigger "IgneoSuite_samples_window" before insert on public."IgneoSuite_samples"
  for each row execute function public."IgneoSuite_check_sample_window"();

alter table public."IgneoSuite_datasets" enable row level security;
alter table public."IgneoSuite_samples" enable row level security;

create policy "IgneoSuite_datasets insert" on public."IgneoSuite_datasets" for insert to anon, authenticated
  with check (status = 'submitted' and consent and (user_id is null or user_id = (select auth.uid())));
create policy "IgneoSuite_datasets read own" on public."IgneoSuite_datasets" for select to authenticated
  using (user_id = (select auth.uid()));
create policy "IgneoSuite_samples insert" on public."IgneoSuite_samples" for insert to anon, authenticated
  with check (dataset_id is not null);
create policy "IgneoSuite_samples read own" on public."IgneoSuite_samples" for select to authenticated
  using (exists (select 1 from public."IgneoSuite_datasets" d where d.id = dataset_id and d.user_id = (select auth.uid())));

grant insert on public."IgneoSuite_datasets", public."IgneoSuite_samples" to anon, authenticated;
grant select on public."IgneoSuite_datasets", public."IgneoSuite_samples", public."IgneoSuite_values" to authenticated;
revoke select on public."IgneoSuite_values" from anon;
revoke update, delete, truncate on public."IgneoSuite_datasets", public."IgneoSuite_samples" from anon, authenticated;
