-- Applied to Supabase project Octa_projects on 2026-11-03 (migration "igneosuite_consent_optional").
-- Saving no longer asks for a consent tick: the column stays (earlier rows keep their value) but is optional.
alter table public."IgneoSuite_datasets" drop constraint if exists "IgneoSuite_datasets_consent_check";
alter table public."IgneoSuite_datasets" alter column consent drop not null;
alter table public."IgneoSuite_datasets" alter column consent drop default;
