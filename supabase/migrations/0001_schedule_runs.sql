-- Run history for generated weekly schedules.
-- Apply with: supabase db push   (or paste into the Supabase SQL editor)

create table if not exists public.schedule_runs (
    id          uuid primary key default gen_random_uuid(),
    user_id     text not null,
    week        date not null,
    format      text not null default 'bullets',
    schedule    text not null,
    flags       jsonb not null default '[]'::jsonb,
    notes       text not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists schedule_runs_user_created_idx
    on public.schedule_runs (user_id, created_at desc);
