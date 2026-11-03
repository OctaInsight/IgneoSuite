-- Link IgneoSuite to the shared Octa user database (User_ tables). Applied 2026-11-03 as "igneosuite_octa_users".
-- Saved projects get an owner when saved while signed in; the owner can list and reopen them without the private key.
alter table public."IgneoSuite_datasets" add column octa_user_id uuid references public."User_accounts"(id) on delete set null;
alter table public."IgneoSuite_runs" add column octa_user_id uuid references public."User_accounts"(id) on delete set null;
alter table public."IgneoSuite_events" add column octa_user_id uuid references public."User_accounts"(id) on delete set null;
alter table public."IgneoSuite_feedback" add column octa_user_id uuid references public."User_accounts"(id) on delete set null;
create index "IgneoSuite_datasets_octa_user_idx" on public."IgneoSuite_datasets" (octa_user_id);

-- user behind a live session token (no side effects); not callable through the API
create or replace function public.octa_user_from_session(p_token text) returns uuid
language sql stable security definer set search_path = '' as $$
  select s.user_id from public."User_sessions" s join public."User_accounts" a on a.id = s.user_id
  where s.token_hash = public.octa_user_hash(coalesce(p_token, '')) and s.expires_at > now() and a.status <> 'suspended'
$$;
revoke execute on function public.octa_user_from_session(text) from public, anon, authenticated;

-- access: the private key, or "session:<token>" of the signed-in owner
create or replace function public.igneosuite_can_access(p_id uuid, p_key text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public."IgneoSuite_datasets" d
    where d.id = p_id
      and ((p_key is not null and char_length(p_key) between 24 and 128
            and d.access_key_hash = public.igneosuite_key_hash(p_key))
           or (p_key like 'session:%' and d.octa_user_id is not null
               and d.octa_user_id = public.octa_user_from_session(substr(p_key, 9)))
           or (d.user_id is not null and d.user_id = (select auth.uid()))))
$$;

-- after saving while signed in, the app claims the project for that user (first owner stays)
create or replace function public.igneosuite_claim(p_id uuid, p_key text, p_session text) returns boolean
language plpgsql volatile security definer set search_path = '' as $$
declare uid uuid := public.octa_user_from_session(p_session);
begin
  if uid is null or not public.igneosuite_can_access(p_id, p_key) then return false; end if;
  update public."IgneoSuite_datasets" set octa_user_id = coalesce(octa_user_id, uid) where id = p_id;
  return true;
end $$;

-- the signed-in user's saved projects
create or replace function public.igneosuite_my_projects(p_session text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', d.id, 'title', d.title, 'n_samples', d.n_samples,
                                               'n_variables', d.n_variables, 'last_step', d.last_step,
                                               'shared', d.shared, 'updated_at', d.updated_at)
                            order by d.updated_at desc), '[]'::jsonb)
  from public."IgneoSuite_datasets" d
  where d.octa_user_id is not null and d.octa_user_id = public.octa_user_from_session(p_session)
$$;

revoke execute on function public.igneosuite_claim(uuid, text, text) from public;
revoke execute on function public.igneosuite_my_projects(text) from public;
grant execute on function public.igneosuite_claim(uuid, text, text) to anon, authenticated;
grant execute on function public.igneosuite_my_projects(text) to anon, authenticated;
