-- Applied to Supabase project Octa_projects on 2026-11-02 (migration "igneosuite_location_required").
-- Location is required for every submitted sample; keep the coordinates as the author wrote them;
-- record whether the author confirmed the locations on the map.
alter table public."IgneoSuite_samples"
  alter column latitude set not null,
  alter column longitude set not null,
  add column latitude_original text check (char_length(latitude_original) <= 60),
  add column longitude_original text check (char_length(longitude_original) <= 60);

alter table public."IgneoSuite_datasets"
  add column location_check text not null default 'not_checked'
    check (location_check in ('confirmed','some_wrong','not_sure','not_checked')),
  add column location_comment text check (char_length(location_comment) <= 2000),
  add column n_with_age integer check (n_with_age >= 0);

alter table public."IgneoSuite_events" drop constraint "IgneoSuite_events_event_check";
alter table public."IgneoSuite_events" add constraint "IgneoSuite_events_event_check"
  check (event in ('load','diagnose','test','fill','export','cluster','about','template','locations','submit'));

create or replace view public."IgneoSuite_values" with (security_invoker = true) as
select s.dataset_id, s.id as sample_row_id, s.sample_id, s.latitude, s.longitude, s.age_ma,
       v.key as variable,
       (s.measured ->> v.key)::double precision as measured,
       (s.estimated ->> v.key)::double precision as estimated,
       (s.estimate_error ->> v.key)::double precision as estimate_error,
       s.latitude_original, s.longitude_original
from public."IgneoSuite_samples" s
cross join lateral (
  select jsonb_object_keys(s.measured) as key
  union
  select jsonb_object_keys(coalesce(s.estimated, '{}'::jsonb))
) v;
revoke select on public."IgneoSuite_values" from anon;
grant select on public."IgneoSuite_values" to authenticated;
