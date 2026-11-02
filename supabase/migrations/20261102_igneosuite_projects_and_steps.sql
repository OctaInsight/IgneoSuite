-- Applied to Supabase project Octa_projects on 2026-11-02 (migration "igneosuite_projects_and_steps").
-- Datasets become saveable projects: saved step by step, reopened later with a private access key
-- (until sign-in exists) or by their owner (user_id = auth.uid()). All writes and reads go through the
-- igneosuite_* functions below, which check the key; the tables themselves stay closed to the public key.

-- datasets: author fields become optional (they will come from the user's account), add project fields
alter table public."IgneoSuite_datasets"
  alter column author_name drop not null,
  alter column author_email drop not null,
  add column access_key_hash text check (char_length(access_key_hash) = 64),
  add column updated_at timestamptz not null default now(),
  add column last_step text check (char_length(last_step) <= 40),
  add column id_column text check (char_length(id_column) <= 200),
  add column column_map jsonb check (pg_column_size(column_map) <= 65536),
  add column shared boolean not null default false;
alter table public."IgneoSuite_datasets" drop constraint "IgneoSuite_datasets_status_check";
alter table public."IgneoSuite_datasets" add constraint "IgneoSuite_datasets_status_check"
  check (status in ('draft','submitted','approved','rejected'));
alter table public."IgneoSuite_datasets" alter column status set default 'draft';
comment on column public."IgneoSuite_datasets".reference is 'DOI or reference of the compilation';
comment on column public."IgneoSuite_datasets".shared is 'Author asked to share the dataset with the IgneoSuite compilation (status becomes submitted)';

-- samples: optional reference and comment for each sample
alter table public."IgneoSuite_samples"
  add column reference text check (char_length(reference) <= 1000),
  add column comment text check (char_length(comment) <= 2000);

-- saved state of each step: settings used and everything produced (statistics, tables, figure data)
create table public."IgneoSuite_steps" (
  dataset_id uuid not null references public."IgneoSuite_datasets"(id) on delete cascade,
  step text not null check (step in ('load','missing','test_scattered','test_block','fill','geometry','clusters')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  app_version text check (char_length(app_version) <= 20),
  params jsonb not null default '{}'::jsonb check (pg_column_size(params) <= 1048576),
  results jsonb not null default '{}'::jsonb check (pg_column_size(results) <= 20971520),
  primary key (dataset_id, step)
);
comment on table public."IgneoSuite_steps" is 'IgneoSuite: saved state of each step of a dataset (settings, statistics, tables and figure data), so work can resume later.';

-- writes now go through the functions only
drop trigger if exists "IgneoSuite_samples_window" on public."IgneoSuite_samples";
drop function if exists public."IgneoSuite_check_sample_window"();
drop policy if exists "IgneoSuite_datasets insert" on public."IgneoSuite_datasets";
drop policy if exists "IgneoSuite_samples insert" on public."IgneoSuite_samples";
revoke insert on public."IgneoSuite_datasets", public."IgneoSuite_samples" from anon, authenticated;

alter table public."IgneoSuite_steps" enable row level security;
create policy "IgneoSuite_steps read own" on public."IgneoSuite_steps" for select to authenticated
  using (exists (select 1 from public."IgneoSuite_datasets" d where d.id = dataset_id and d.user_id = (select auth.uid())));
grant select on public."IgneoSuite_steps" to authenticated;
revoke insert, update, delete, truncate on public."IgneoSuite_steps" from anon, authenticated;

create index "IgneoSuite_datasets_updated_idx" on public."IgneoSuite_datasets" (updated_at);

-- ---------------------------------------------------------------- functions
create or replace function public.igneosuite_key_hash(p_key text)
returns text language sql immutable set search_path = '' as $$
  select encode(extensions.digest(p_key, 'sha256'), 'hex')
$$;
revoke execute on function public.igneosuite_key_hash(text) from public, anon, authenticated;

create or replace function public.igneosuite_can_access(p_id uuid, p_key text)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public."IgneoSuite_datasets" d
    where d.id = p_id
      and ((p_key is not null and char_length(p_key) between 24 and 128
            and d.access_key_hash = public.igneosuite_key_hash(p_key))
           or (d.user_id is not null and d.user_id = (select auth.uid()))))
$$;
revoke execute on function public.igneosuite_can_access(uuid, text) from public, anon, authenticated;

-- create or update the dataset (project) row
create or replace function public.igneosuite_save_dataset(p_id uuid, p_key text, p_meta jsonb)
returns void language plpgsql security definer set search_path = '' as $$
declare m jsonb := coalesce(p_meta, '{}'::jsonb);
begin
  if p_key is null or char_length(p_key) not between 24 and 128 then
    raise exception 'invalid access key';
  end if;
  if exists (select 1 from public."IgneoSuite_datasets" where id = p_id) then
    if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not allowed'; end if;
    update public."IgneoSuite_datasets" set
      title = coalesce(m->>'title', title),
      reference = case when m ? 'reference' then m->>'reference' else reference end,
      description = case when m ? 'description' then m->>'description' else description end,
      author_name = case when m ? 'author_name' then m->>'author_name' else author_name end,
      author_email = case when m ? 'author_email' then m->>'author_email' else author_email end,
      affiliation = case when m ? 'affiliation' then m->>'affiliation' else affiliation end,
      licence = coalesce(m->>'licence', licence),
      shared = coalesce((m->>'shared')::boolean, shared),
      status = case when coalesce((m->>'shared')::boolean, shared) and status = 'draft' then 'submitted'
                    when not coalesce((m->>'shared')::boolean, shared) and status = 'submitted' then 'draft'
                    else status end,
      n_samples = coalesce((m->>'n_samples')::int, n_samples),
      n_variables = coalesce((m->>'n_variables')::int, n_variables),
      variables = case when m ? 'variables' then array(select jsonb_array_elements_text(m->'variables')) else variables end,
      id_column = coalesce(m->>'id_column', id_column),
      column_map = coalesce(m->'column_map', column_map),
      location_check = coalesce(m->>'location_check', location_check),
      location_comment = case when m ? 'location_comment' then m->>'location_comment' else location_comment end,
      n_with_age = coalesce((m->>'n_with_age')::int, n_with_age),
      estimation_method = case when m ? 'estimation_method' then m->>'estimation_method' else estimation_method end,
      error_band = case when m ? 'error_band' then (m->>'error_band')::real else error_band end,
      app_version = coalesce(m->>'app_version', app_version),
      session_id = coalesce(m->>'session_id', session_id),
      updated_at = now()
    where id = p_id;
  else
    insert into public."IgneoSuite_datasets"(id, access_key_hash, user_id, title, reference, description,
      author_name, author_email, affiliation, licence, consent, shared, status, n_samples, n_variables,
      variables, id_column, column_map, location_check, location_comment, n_with_age, app_version, session_id)
    values (p_id, public.igneosuite_key_hash(p_key), (select auth.uid()), m->>'title', m->>'reference',
      m->>'description', m->>'author_name', m->>'author_email', m->>'affiliation',
      coalesce(m->>'licence', 'CC-BY-4.0'), coalesce((m->>'consent')::boolean, false),
      coalesce((m->>'shared')::boolean, false),
      case when coalesce((m->>'shared')::boolean, false) then 'submitted' else 'draft' end,
      (m->>'n_samples')::int, (m->>'n_variables')::int,
      array(select jsonb_array_elements_text(coalesce(m->'variables', '[]'::jsonb))),
      m->>'id_column', m->'column_map', coalesce(m->>'location_check', 'not_checked'),
      m->>'location_comment', (m->>'n_with_age')::int, m->>'app_version', m->>'session_id');
  end if;
end $$;

-- add sample rows (p_first = true replaces all samples of the dataset)
create or replace function public.igneosuite_save_samples(p_id uuid, p_key text, p_rows jsonb, p_first boolean)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 1000 then
    raise exception 'send between 0 and 1000 samples per call';
  end if;
  if p_first then
    delete from public."IgneoSuite_samples" where dataset_id = p_id;
  end if;
  insert into public."IgneoSuite_samples"(dataset_id, row_number, sample_id, latitude, longitude, age_ma,
      latitude_original, longitude_original, reference, comment, measured, estimated, estimate_error)
  select p_id, r.row_number, r.sample_id, r.latitude, r.longitude, r.age_ma, r.latitude_original,
         r.longitude_original, r.reference, r.comment, coalesce(r.measured, '{}'::jsonb), r.estimated, r.estimate_error
  from jsonb_to_recordset(p_rows) as r(row_number int, sample_id text, latitude double precision,
       longitude double precision, age_ma double precision, latitude_original text, longitude_original text,
       reference text, comment text, measured jsonb, estimated jsonb, estimate_error jsonb);
  get diagnostics n = row_count;
  update public."IgneoSuite_datasets" set updated_at = now() where id = p_id;
  return n;
end $$;

-- store gap-filled values and their errors (step 4)
create or replace function public.igneosuite_save_estimates(p_id uuid, p_key text, p_rows jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 1000 then
    raise exception 'send between 0 and 1000 samples per call';
  end if;
  update public."IgneoSuite_samples" s set estimated = r.estimated, estimate_error = r.estimate_error
  from jsonb_to_recordset(p_rows) as r(row_number int, estimated jsonb, estimate_error jsonb)
  where s.dataset_id = p_id and s.row_number = r.row_number;
  get diagnostics n = row_count;
  return n;
end $$;

-- save one step's settings and results
create or replace function public.igneosuite_save_step(p_id uuid, p_key text, p_step text, p_params jsonb,
                                                       p_results jsonb, p_app_version text)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not allowed'; end if;
  insert into public."IgneoSuite_steps"(dataset_id, step, params, results, app_version)
  values (p_id, p_step, coalesce(p_params, '{}'::jsonb), coalesce(p_results, '{}'::jsonb), p_app_version)
  on conflict (dataset_id, step) do update
    set params = excluded.params, results = excluded.results, app_version = excluded.app_version, updated_at = now();
  update public."IgneoSuite_datasets" set last_step = p_step, updated_at = now() where id = p_id;
end $$;

-- remove a step that is no longer valid (e.g. tests repeated with other settings)
create or replace function public.igneosuite_delete_step(p_id uuid, p_key text, p_step text)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not allowed'; end if;
  delete from public."IgneoSuite_steps" where dataset_id = p_id and step = p_step;
end $$;

-- read a saved dataset with all its steps (not the samples)
create or replace function public.igneosuite_load_dataset(p_id uuid, p_key text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare out jsonb;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not found or not allowed'; end if;
  select jsonb_build_object(
    'dataset', to_jsonb(d) - 'access_key_hash' - 'session_id',
    'steps', coalesce((select jsonb_object_agg(s.step, jsonb_build_object('params', s.params, 'results', s.results,
                                                                           'updated_at', s.updated_at))
                       from public."IgneoSuite_steps" s where s.dataset_id = d.id), '{}'::jsonb))
  into out from public."IgneoSuite_datasets" d where d.id = p_id;
  return out;
end $$;

-- read samples page by page
create or replace function public.igneosuite_load_samples(p_id uuid, p_key text, p_offset integer, p_limit integer)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare out jsonb;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not found or not allowed'; end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.row_number), '[]'::jsonb) into out from (
    select row_number, sample_id, latitude, longitude, age_ma, latitude_original, longitude_original,
           reference, comment, measured, estimated, estimate_error
    from public."IgneoSuite_samples" where dataset_id = p_id
    order by row_number offset greatest(p_offset, 0) limit least(greatest(p_limit, 1), 2000)) x;
  return out;
end $$;

revoke execute on function public.igneosuite_save_dataset(uuid, text, jsonb) from public;
revoke execute on function public.igneosuite_save_samples(uuid, text, jsonb, boolean) from public;
revoke execute on function public.igneosuite_save_estimates(uuid, text, jsonb) from public;
revoke execute on function public.igneosuite_save_step(uuid, text, text, jsonb, jsonb, text) from public;
revoke execute on function public.igneosuite_delete_step(uuid, text, text) from public;
revoke execute on function public.igneosuite_load_dataset(uuid, text) from public;
revoke execute on function public.igneosuite_load_samples(uuid, text, integer, integer) from public;
grant execute on function public.igneosuite_save_dataset(uuid, text, jsonb) to anon, authenticated;
grant execute on function public.igneosuite_save_samples(uuid, text, jsonb, boolean) to anon, authenticated;
grant execute on function public.igneosuite_save_estimates(uuid, text, jsonb) to anon, authenticated;
grant execute on function public.igneosuite_save_step(uuid, text, text, jsonb, jsonb, text) to anon, authenticated;
grant execute on function public.igneosuite_delete_step(uuid, text, text) to anon, authenticated;
grant execute on function public.igneosuite_load_dataset(uuid, text) to anon, authenticated;
grant execute on function public.igneosuite_load_samples(uuid, text, integer, integer) to anon, authenticated;

-- events: allow the new event names
alter table public."IgneoSuite_events" drop constraint "IgneoSuite_events_event_check";
alter table public."IgneoSuite_events" add constraint "IgneoSuite_events_event_check"
  check (event in ('load','diagnose','test','fill','export','cluster','about','template','locations','submit',
                   'save','resume','geometry'));
