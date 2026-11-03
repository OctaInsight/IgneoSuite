-- Sharing saved IgneoSuite projects with other Octa users. Applied 2026-11-03 as "igneosuite_project_sharing".
-- The owner shares a project with an email address (an existing Octa user, or an invitation that applies
-- once someone registers with that email), as viewer or editor.
create table public."IgneoSuite_shares" (
  dataset_id uuid not null references public."IgneoSuite_datasets"(id) on delete cascade,
  email text not null check (email = lower(email) and char_length(email) <= 254),
  role text not null default 'view' check (role in ('view', 'edit')),
  created_at timestamptz not null default now(),
  created_by uuid references public."User_accounts"(id) on delete set null,
  primary key (dataset_id, email)
);
create index "IgneoSuite_shares_email_idx" on public."IgneoSuite_shares" (email);
alter table public."IgneoSuite_shares" enable row level security;
revoke all on public."IgneoSuite_shares" from anon, authenticated;
comment on table public."IgneoSuite_shares" is 'Projects shared by their owner with other people (by email; works for invited people once they register).';

-- role of the signed-in user ("session:<token>" key) on a project: owner / edit / view / null
create or replace function public.igneosuite_session_role(p_id uuid, p_key text) returns text
language sql stable security definer set search_path = '' as $$
  select case when p_key is null or p_key not like 'session:%' then null
              when d.octa_user_id = u.id then 'owner'
              else (select s.role from public."IgneoSuite_shares" s where s.dataset_id = d.id and s.email = u.email) end
  from public."IgneoSuite_datasets" d,
       public."User_accounts" u
  where d.id = p_id and u.id = public.octa_user_from_session(substr(p_key, 9))
$$;

-- reading: private key, owner, anyone it is shared with, or the old Supabase-auth owner
create or replace function public.igneosuite_can_access(p_id uuid, p_key text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public."IgneoSuite_datasets" d
    where d.id = p_id
      and ((p_key is not null and char_length(p_key) between 24 and 128
            and d.access_key_hash = public.igneosuite_key_hash(p_key))
           or public.igneosuite_session_role(p_id, p_key) is not null
           or (d.user_id is not null and d.user_id = (select auth.uid()))))
$$;

-- writing: private key, owner, or people it is shared with as editor
create or replace function public.igneosuite_can_edit(p_id uuid, p_key text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public."IgneoSuite_datasets" d
    where d.id = p_id
      and ((p_key is not null and char_length(p_key) between 24 and 128
            and d.access_key_hash = public.igneosuite_key_hash(p_key))
           or public.igneosuite_session_role(p_id, p_key) in ('owner', 'edit')
           or (d.user_id is not null and d.user_id = (select auth.uid()))))
$$;
revoke execute on function public.igneosuite_session_role(uuid, text) from public, anon, authenticated;
revoke execute on function public.igneosuite_can_edit(uuid, text) from public, anon, authenticated;

-- the save functions check edit rights instead of read rights
do $$ declare f record; def text; begin
  for f in select p.oid from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in ('igneosuite_save_dataset', 'igneosuite_save_samples',
                 'igneosuite_save_estimates', 'igneosuite_save_step', 'igneosuite_delete_step') loop
    def := replace(pg_get_functiondef(f.oid), 'public.igneosuite_can_access(', 'public.igneosuite_can_edit(');
    execute def;
  end loop;
end $$;

-- projects shared with the signed-in user
create or replace function public.igneosuite_shared_with_me(p_session text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', d.id, 'title', d.title, 'n_samples', d.n_samples,
           'last_step', d.last_step, 'updated_at', d.updated_at, 'role', s.role,
           'owner', concat_ws(' ', o.first_name, o.last_name), 'owner_username', o.username)
           order by d.updated_at desc), '[]'::jsonb)
  from public."User_accounts" u
  join public."IgneoSuite_shares" s on s.email = u.email
  join public."IgneoSuite_datasets" d on d.id = s.dataset_id
  left join public."User_accounts" o on o.id = d.octa_user_id
  where u.id = public.octa_user_from_session(p_session)
$$;

-- find Octa users to share with (signed-in users only; by username, name or exact email; no emails returned)
create or replace function public.igneosuite_find_users(p_session text, p_query text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('username', a.username,
           'name', concat_ws(' ', a.first_name, a.last_name), 'affiliation', a.affiliation) order by a.username), '[]'::jsonb)
  from (select * from public."User_accounts" a
        where public.octa_user_from_session(p_session) is not null and a.status = 'active'
          and char_length(trim(coalesce(p_query, ''))) >= 3
          and a.id <> public.octa_user_from_session(p_session)
          and (a.email = lower(trim(p_query)) or a.username ilike '%' || trim(p_query) || '%'
               or concat_ws(' ', a.first_name, a.last_name) ilike '%' || trim(p_query) || '%')
        limit 10) a
$$;

-- owner: share with usernames and/or emails. Returns who was added and their email, so the app can notify them.
create or replace function public.igneosuite_share(p_session text, p_id uuid, p_people text[], p_role text) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare me uuid := public.octa_user_from_session(p_session); x text; em text; acc public."User_accounts"; out jsonb := '[]'::jsonb;
begin
  if me is null or not exists (select 1 from public."IgneoSuite_datasets" where id = p_id and octa_user_id = me) then
    return jsonb_build_object('ok', false, 'error', 'Only the owner of the project can share it.');
  end if;
  if p_role not in ('view', 'edit') then return jsonb_build_object('ok', false, 'error', 'bad role'); end if;
  if coalesce(array_length(p_people, 1), 0) > 50 then return jsonb_build_object('ok', false, 'error', 'At most 50 people at a time.'); end if;
  foreach x in array coalesce(p_people, '{}') loop
    x := lower(trim(x));
    continue when x = '';
    acc := null;
    select * into acc from public."User_accounts" where email = x or lower(username) = x limit 1;
    em := coalesce(acc.email, case when x ~ '^[^@\s]+@[^@\s]+\.[^@\s]{2,}$' then x end);
    if em is null then
      out := out || jsonb_build_object('person', x, 'status', 'unknown');
      continue;
    end if;
    if acc.id = me then continue; end if;
    insert into public."IgneoSuite_shares"(dataset_id, email, role, created_by) values (p_id, em, p_role, me)
    on conflict (dataset_id, email) do update set role = excluded.role;
    out := out || jsonb_build_object('person', x, 'email', em, 'status', case when acc.id is null then 'invited' else 'user' end,
                                     'name', nullif(concat_ws(' ', acc.first_name, acc.last_name), ''), 'username', acc.username);
  end loop;
  return jsonb_build_object('ok', true, 'added', out,
    'project', (select title from public."IgneoSuite_datasets" where id = p_id),
    'by', (select concat_ws(' ', first_name, last_name) from public."User_accounts" where id = me));
end $$;

-- owner: who the project is shared with
create or replace function public.igneosuite_shares(p_session text, p_id uuid) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('email', s.email, 'role', s.role, 'since', s.created_at,
           'name', nullif(concat_ws(' ', a.first_name, a.last_name), ''), 'username', a.username,
           'registered', a.id is not null) order by s.created_at), '[]'::jsonb)
  from public."IgneoSuite_shares" s
  left join public."User_accounts" a on a.email = s.email
  where s.dataset_id = p_id
    and exists (select 1 from public."IgneoSuite_datasets" d where d.id = p_id
                and d.octa_user_id = public.octa_user_from_session(p_session))
$$;

create or replace function public.igneosuite_unshare(p_session text, p_id uuid, p_email text) returns boolean
language plpgsql volatile security definer set search_path = '' as $$
begin
  if not exists (select 1 from public."IgneoSuite_datasets" where id = p_id
                 and octa_user_id = public.octa_user_from_session(p_session)) then return false; end if;
  delete from public."IgneoSuite_shares" where dataset_id = p_id and email = lower(trim(p_email));
  return true;
end $$;

-- the role of the signed-in user on a project (for the app: owner / edit / view)
create or replace function public.igneosuite_my_role(p_session text, p_id uuid) returns text
language sql stable security definer set search_path = '' as $$
  select public.igneosuite_session_role(p_id, 'session:' || coalesce(p_session, ''))
$$;

do $$ declare f text; begin
  foreach f in array array['igneosuite_shared_with_me(text)', 'igneosuite_find_users(text,text)',
                           'igneosuite_share(text,uuid,text[],text)', 'igneosuite_shares(text,uuid)',
                           'igneosuite_unshare(text,uuid,text)', 'igneosuite_my_role(text,uuid)'] loop
    execute format('revoke execute on function public.%s from public', f);
    execute format('grant execute on function public.%s to anon, authenticated', f);
  end loop;
end $$;
