-- Deleting a saved project: the owner asks, an Octa administrator approves. Applied 2026-11-04 as
-- "igneosuite_delete_requests". On approval the project row is deleted; its samples (with estimates), the
-- saved steps and all shares go with it (foreign keys with on delete cascade). The request row is kept as a record.
create table public."IgneoSuite_delete_requests" (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  dataset_id uuid not null,                          -- no foreign key: the record outlives the project
  title text,
  n_samples integer,
  requested_by uuid references public."User_accounts"(id) on delete set null,
  reason text check (char_length(reason) <= 2000),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'cancelled')),
  decided_by uuid references public."User_accounts"(id) on delete set null,
  decided_at timestamptz,
  admin_comment text check (char_length(admin_comment) <= 2000)
);
create unique index "IgneoSuite_delete_requests_one_pending" on public."IgneoSuite_delete_requests" (dataset_id)
  where status = 'pending';
alter table public."IgneoSuite_delete_requests" enable row level security;
revoke all on public."IgneoSuite_delete_requests" from anon, authenticated;
comment on table public."IgneoSuite_delete_requests" is 'Requests by project owners to delete a saved project; carried out only after an administrator approves.';

create or replace function public.igneosuite_is_admin(p_session text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public."User_accounts" where id = public.octa_user_from_session(p_session) and role = 'admin')
$$;
revoke execute on function public.igneosuite_is_admin(text) from public, anon, authenticated;

-- owner: ask for deletion
create or replace function public.igneosuite_request_delete(p_session text, p_id uuid, p_reason text) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare me uuid := public.octa_user_from_session(p_session); d public."IgneoSuite_datasets";
begin
  select * into d from public."IgneoSuite_datasets" where id = p_id;
  if me is null or d.id is null or d.octa_user_id is distinct from me then
    return jsonb_build_object('ok', false, 'error', 'Only the owner of the project can ask for it to be deleted.');
  end if;
  if exists (select 1 from public."IgneoSuite_delete_requests" where dataset_id = p_id and status = 'pending') then
    return jsonb_build_object('ok', false, 'error', 'A deletion request for this project is already waiting for approval.');
  end if;
  insert into public."IgneoSuite_delete_requests"(dataset_id, title, n_samples, requested_by, reason)
  values (p_id, d.title, d.n_samples, me, left(nullif(trim(p_reason), ''), 2000));
  return jsonb_build_object('ok', true, 'title', d.title,
    'by', (select concat_ws(' ', first_name, last_name) || ' (' || email || ')' from public."User_accounts" where id = me));
end $$;

-- owner: withdraw the request
create or replace function public.igneosuite_cancel_delete(p_session text, p_id uuid) returns boolean
language plpgsql volatile security definer set search_path = '' as $$
begin
  update public."IgneoSuite_delete_requests" set status = 'cancelled', decided_at = now()
  where dataset_id = p_id and status = 'pending' and requested_by = public.octa_user_from_session(p_session)
    and requested_by is not null;
  return found;
end $$;

-- my projects, now with any pending deletion request
create or replace function public.igneosuite_my_projects(p_session text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', d.id, 'title', d.title, 'n_samples', d.n_samples,
                                               'n_variables', d.n_variables, 'last_step', d.last_step,
                                               'shared', d.shared, 'updated_at', d.updated_at,
                                               'n_shares', (select count(*) from public."IgneoSuite_shares" s where s.dataset_id = d.id),
                                               'delete_requested', r.created_at, 'delete_reason', r.reason)
                            order by d.updated_at desc), '[]'::jsonb)
  from public."IgneoSuite_datasets" d
  left join public."IgneoSuite_delete_requests" r on r.dataset_id = d.id and r.status = 'pending'
  where d.octa_user_id is not null and d.octa_user_id = public.octa_user_from_session(p_session)
$$;

-- administrator: list requests (pending first, then the last 50 decided)
create or replace function public.igneosuite_admin_delete_requests(p_session text) returns jsonb
language sql stable security definer set search_path = '' as $$
  select case when not public.igneosuite_is_admin(p_session) then jsonb_build_object('ok', false, 'error', 'Admins only.')
  else jsonb_build_object('ok', true, 'requests', coalesce((
    select jsonb_agg(x order by (x->>'status') <> 'pending', x->>'created_at' desc) from (
      select jsonb_build_object('id', r.id, 'created_at', r.created_at, 'dataset_id', r.dataset_id, 'title', r.title,
             'n_samples', r.n_samples, 'reason', r.reason, 'status', r.status, 'admin_comment', r.admin_comment,
             'decided_at', r.decided_at, 'exists', d.id is not null,
             'n_shares', (select count(*) from public."IgneoSuite_shares" s where s.dataset_id = r.dataset_id),
             'owner', concat_ws(' ', a.first_name, a.last_name), 'owner_email', a.email,
             'decided_by', concat_ws(' ', b.first_name, b.last_name)) x
      from public."IgneoSuite_delete_requests" r
      left join public."IgneoSuite_datasets" d on d.id = r.dataset_id
      left join public."User_accounts" a on a.id = r.requested_by
      left join public."User_accounts" b on b.id = r.decided_by
      where r.status = 'pending' or r.id in (select id from public."IgneoSuite_delete_requests"
                                              where status <> 'pending' order by decided_at desc nulls last limit 50)) q
  ), '[]'::jsonb)) end
$$;

-- administrator: approve (deletes the project and everything linked to it) or reject
create or replace function public.igneosuite_admin_decide_delete(p_session text, p_request bigint, p_approve boolean,
                                                                 p_comment text) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare me uuid := public.octa_user_from_session(p_session); r public."IgneoSuite_delete_requests";
begin
  if not public.igneosuite_is_admin(p_session) then return jsonb_build_object('ok', false, 'error', 'Admins only.'); end if;
  select * into r from public."IgneoSuite_delete_requests" where id = p_request for update;
  if r.id is null or r.status <> 'pending' then
    return jsonb_build_object('ok', false, 'error', 'This request is no longer waiting for a decision.');
  end if;
  if p_approve then
    delete from public."IgneoSuite_datasets" where id = r.dataset_id;   -- samples, steps and shares cascade
  end if;
  update public."IgneoSuite_delete_requests"
  set status = case when p_approve then 'approved' else 'rejected' end, decided_by = me, decided_at = now(),
      admin_comment = left(nullif(trim(p_comment), ''), 2000)
  where id = r.id;
  return jsonb_build_object('ok', true, 'status', case when p_approve then 'approved' else 'rejected' end,
    'title', r.title,
    'owner_email', (select email from public."User_accounts" where id = r.requested_by),
    'owner_name', (select concat_ws(' ', first_name, last_name) from public."User_accounts" where id = r.requested_by));
end $$;

do $$ declare f text; begin
  foreach f in array array['igneosuite_request_delete(text,uuid,text)', 'igneosuite_cancel_delete(text,uuid)',
                           'igneosuite_my_projects(text)', 'igneosuite_admin_delete_requests(text)',
                           'igneosuite_admin_decide_delete(text,bigint,boolean,text)'] loop
    execute format('revoke execute on function public.%s from public', f);
    execute format('grant execute on function public.%s to anon, authenticated', f);
  end loop;
end $$;
