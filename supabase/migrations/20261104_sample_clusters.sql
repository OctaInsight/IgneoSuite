-- Per-sample cluster numbers and error ranges. Applied 2026-11-04 as "igneosuite_sample_clusters".
-- Each sample row now holds everything the step-6 Excel file shows: measured, estimated, ± error, the error range
-- (low, high) of every estimate, and the cluster before (reference run) and after gap-filling.
alter table public."IgneoSuite_samples"
  add column cluster_reference smallint,
  add column cluster_filled smallint,
  add column estimate_range jsonb;
comment on column public."IgneoSuite_samples".cluster_reference is 'Cluster in the reference run (measured values of the reference variables only); null if the sample was not in that run.';
comment on column public."IgneoSuite_samples".cluster_filled is 'Cluster in the run on the gap-filled data; null if the sample was not clustered.';
comment on column public."IgneoSuite_samples".estimate_range is 'Error range of each estimated value: {"variable": [low, high]} (the chosen error band, e.g. 68%).';

create or replace function public.igneosuite_save_samples(p_id uuid, p_key text, p_rows jsonb, p_first boolean)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_edit(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 1000 then
    raise exception 'send between 0 and 1000 samples per call';
  end if;
  if p_first then
    delete from public."IgneoSuite_samples" where dataset_id = p_id;
  end if;
  insert into public."IgneoSuite_samples"(dataset_id, row_number, sample_id, latitude, longitude, age_ma,
      latitude_original, longitude_original, reference, comment, measured, estimated, estimate_error,
      estimate_range, cluster_reference, cluster_filled)
  select p_id, r.row_number, r.sample_id, r.latitude, r.longitude, r.age_ma, r.latitude_original,
         r.longitude_original, r.reference, r.comment, coalesce(r.measured, '{}'::jsonb), r.estimated, r.estimate_error,
         r.estimate_range, r.cluster_reference, r.cluster_filled
  from jsonb_to_recordset(p_rows) as r(row_number int, sample_id text, latitude double precision,
       longitude double precision, age_ma double precision, latitude_original text, longitude_original text,
       reference text, comment text, measured jsonb, estimated jsonb, estimate_error jsonb, estimate_range jsonb,
       cluster_reference smallint, cluster_filled smallint);
  get diagnostics n = row_count;
  update public."IgneoSuite_datasets" set updated_at = now() where id = p_id;
  return n;
end $$;

create or replace function public.igneosuite_save_estimates(p_id uuid, p_key text, p_rows jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_edit(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 1000 then
    raise exception 'send between 0 and 1000 samples per call';
  end if;
  update public."IgneoSuite_samples" s set estimated = r.estimated, estimate_error = r.estimate_error,
         estimate_range = r.estimate_range
  from jsonb_to_recordset(p_rows) as r(row_number int, estimated jsonb, estimate_error jsonb, estimate_range jsonb)
  where s.dataset_id = p_id and s.row_number = r.row_number;
  get diagnostics n = row_count;
  return n;
end $$;

-- cluster numbers only (step 6 saved without re-sending the samples). p_rows: [{"row_number", "a", "b"}];
-- p_first clears the numbers of every sample first (samples not in the run stay empty).
create or replace function public.igneosuite_save_clusters(p_id uuid, p_key text, p_rows jsonb, p_first boolean)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_edit(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 5000 then
    raise exception 'send between 0 and 5000 samples per call';
  end if;
  if p_first then
    update public."IgneoSuite_samples" set cluster_reference = null, cluster_filled = null where dataset_id = p_id;
  end if;
  update public."IgneoSuite_samples" s set cluster_reference = r.a, cluster_filled = r.b
  from jsonb_to_recordset(p_rows) as r(row_number int, a smallint, b smallint)
  where s.dataset_id = p_id and s.row_number = r.row_number;
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function public.igneosuite_load_samples(p_id uuid, p_key text, p_offset integer, p_limit integer)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare out jsonb;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not found or not allowed'; end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.row_number), '[]'::jsonb) into out from (
    select row_number, sample_id, latitude, longitude, age_ma, latitude_original, longitude_original,
           reference, comment, measured, estimated, estimate_error, estimate_range, cluster_reference, cluster_filled
    from public."IgneoSuite_samples" where dataset_id = p_id
    order by row_number offset greatest(p_offset, 0) limit least(greatest(p_limit, 1), 2000)) x;
  return out;
end $$;

revoke execute on function public.igneosuite_save_clusters(uuid, text, jsonb, boolean) from public;
grant execute on function public.igneosuite_save_clusters(uuid, text, jsonb, boolean) to anon, authenticated;
