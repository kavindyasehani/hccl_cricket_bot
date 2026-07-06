-- HCCL Hand Cricket Telegram Bot tables
-- Run this in Supabase SQL Editor before deploying the bot.

create extension if not exists pgcrypto;

create table if not exists public.hccl_cricket_players (
  telegram_id bigint primary key,
  username text,
  first_name text,
  last_name text,
  registered_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  games_played integer not null default 0,
  wins integer not null default 0,
  losses integer not null default 0,
  draws integer not null default 0,
  total_runs integer not null default 0,
  total_wickets integer not null default 0
);

create table if not exists public.hccl_cricket_games (
  id uuid primary key default gen_random_uuid(),
  chat_id bigint not null,
  message_id bigint,
  creator_id bigint not null references public.hccl_cricket_players(telegram_id),
  opponent_id bigint references public.hccl_cricket_players(telegram_id),

  mode text not null default 'normal' check (mode in ('normal', 'one_three', 'no_five')),
  status text not null default 'waiting' check (status in ('waiting', 'toss', 'playing', 'finished', 'cancelled')),

  innings integer not null default 1,
  toss_winner_id bigint references public.hccl_cricket_players(telegram_id),
  batter_id bigint references public.hccl_cricket_players(telegram_id),
  bowler_id bigint references public.hccl_cricket_players(telegram_id),
  first_batter_id bigint references public.hccl_cricket_players(telegram_id),
  first_bowler_id bigint references public.hccl_cricket_players(telegram_id),

  innings1_score integer not null default 0,
  innings2_score integer not null default 0,
  innings1_out boolean not null default false,
  innings2_out boolean not null default false,
  target integer,

  current_score integer not null default 0,
  balls integer not null default 0,
  batter_choice integer,
  bowler_choice integer,

  winner_id bigint references public.hccl_cricket_players(telegram_id),
  stats_applied boolean not null default false,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.hccl_cricket_balls (
  id bigint generated always as identity primary key,
  game_id uuid not null references public.hccl_cricket_games(id) on delete cascade,
  chat_id bigint not null,
  innings integer not null,
  ball_no integer not null,
  batter_id bigint not null references public.hccl_cricket_players(telegram_id),
  bowler_id bigint not null references public.hccl_cricket_players(telegram_id),
  batter_pick integer not null,
  bowler_pick integer not null,
  runs integer not null,
  is_out boolean not null default false,
  total_after integer not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_hccl_cricket_games_chat_status
  on public.hccl_cricket_games(chat_id, status, created_at desc);

create index if not exists idx_hccl_cricket_balls_game
  on public.hccl_cricket_balls(game_id, innings, ball_no);
