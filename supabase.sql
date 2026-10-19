-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run

create table if not exists public.users (
  id         bigint primary key,
  full_name  text,
  username   text,
  first_seen timestamptz default now(),
  last_seen  timestamptz default now(),
  uses       integer default 1
);

-- Insert new user, or bump uses/last_seen for an existing one (atomic)
create or replace function public.log_user(p_id bigint, p_name text, p_username text)
returns void
language sql
as $$
  insert into public.users (id, full_name, username)
  values (p_id, p_name, p_username)
  on conflict (id) do update
    set last_seen = now(),
        uses      = public.users.uses + 1,
        full_name = excluded.full_name,
        username  = excluded.username;
$$;

-- Lock the table down: only the service_role key (used by the bot) can touch it.
alter table public.users enable row level security;
