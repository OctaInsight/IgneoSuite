-- IgneoSuite 2 (module "Plot and explore"): age groups per sample. Applied 2026-11-04 as "igneosuite_age_groups".
-- The grouping itself (method, intervals, names, colours) is saved as the project step "age_groups";
-- each sample row keeps the name of its group.
alter table public."IgneoSuite_samples" add column age_group text check (char_length(age_group) <= 100);
comment on column public."IgneoSuite_samples".age_group is 'Age group the sample belongs to (step 2 of the Plot and explore module); null without an age or grouping.';

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
      estimate_range, cluster_reference, cluster_filled, age_group)
  select p_id, r.row_number, r.sample_id, r.latitude, r.longitude, r.age_ma, r.latitude_original,
         r.longitude_original, r.reference, r.comment, coalesce(r.measured, '{}'::jsonb), r.estimated, r.estimate_error,
         r.estimate_range, r.cluster_reference, r.cluster_filled, left(r.age_group, 100)
  from jsonb_to_recordset(p_rows) as r(row_number int, sample_id text, latitude double precision,
       longitude double precision, age_ma double precision, latitude_original text, longitude_original text,
       reference text, comment text, measured jsonb, estimated jsonb, estimate_error jsonb, estimate_range jsonb,
       cluster_reference smallint, cluster_filled smallint, age_group text);
  get diagnostics n = row_count;
  update public."IgneoSuite_datasets" set updated_at = now() where id = p_id;
  return n;
end $$;

-- age groups only. p_rows: [{"row_number", "g"}]; p_first clears every sample's group first.
create or replace function public.igneosuite_save_age_groups(p_id uuid, p_key text, p_rows jsonb, p_first boolean)
returns integer language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.igneosuite_can_edit(p_id, p_key) then raise exception 'not allowed'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 5000 then
    raise exception 'send between 0 and 5000 samples per call';
  end if;
  if p_first then
    update public."IgneoSuite_samples" set age_group = null where dataset_id = p_id;
  end if;
  update public."IgneoSuite_samples" s set age_group = left(r.g, 100)
  from jsonb_to_recordset(p_rows) as r(row_number int, g text)
  where s.dataset_id = p_id and s.row_number = r.row_number;
  get diagnostics n = row_count;
  update public."IgneoSuite_datasets" set updated_at = now() where id = p_id;
  return n;
end $$;

create or replace function public.igneosuite_load_samples(p_id uuid, p_key text, p_offset integer, p_limit integer)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare out jsonb;
begin
  if not public.igneosuite_can_access(p_id, p_key) then raise exception 'not found or not allowed'; end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.row_number), '[]'::jsonb) into out from (
    select row_number, sample_id, latitude, longitude, age_ma, latitude_original, longitude_original,
           reference, comment, measured, estimated, estimate_error, estimate_range, cluster_reference, cluster_filled,
           age_group
    from public."IgneoSuite_samples" where dataset_id = p_id
    order by row_number offset greatest(p_offset, 0) limit least(greatest(p_limit, 1), 2000)) x;
  return out;
end $$;

revoke execute on function public.igneosuite_save_age_groups(uuid, text, jsonb, boolean) from public;
grant execute on function public.igneosuite_save_age_groups(uuid, text, jsonb, boolean) to anon, authenticated;
