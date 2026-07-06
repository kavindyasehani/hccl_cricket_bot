# HCCL Hand Cricket Telegram Bot

This is a Vercel-compatible Telegram webhook bot for a two-player hand cricket game.

## Features

- `/start` registers a player.
- `/cricket` starts a group challenge.
- Another registered player taps **Join Game**.
- Creator can choose mode before the opponent joins.
- Bot handles toss, bat/bowl choice, innings, chase, out, final result, and stats.
- Supports three modes:
  - **Default**: 1, 2, 3, 4, 5, 6
  - **1-3 Mode**: 1, 2, 3
  - **No 5 Mode**: 1, 2, 3, 4, 0, 6

## Files

```text
api/telegram.py
requirements.txt
supabase_schema.sql
.env.example
README_CRICKET_BOT.md
```

## Supabase setup

1. Open Supabase.
2. Go to **SQL Editor**.
3. Paste and run `supabase_schema.sql`.

Use the `service_role` key in Vercel if your tables use RLS. If RLS is disabled for these bot-only tables, the anon key can work, but the service role key is better for a server-side webhook.

## Vercel environment variables

Add these in Vercel Project Settings → Environment Variables:

```text
TELEGRAM_BOT_TOKEN
SUPABASE_URL
SUPABASE_KEY
WEBHOOK_SECRET
```

Your existing live endpoint can stay:

```text
https://hccl-telegram-vercel-bot.vercel.app/api/telegram
```

## Set Telegram webhook

Recommended method using Telegram's webhook secret header:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://hccl-telegram-vercel-bot.vercel.app/api/telegram&secret_token=<WEBHOOK_SECRET>
```

Alternative method using a query secret:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://hccl-telegram-vercel-bot.vercel.app/api/telegram?secret=<WEBHOOK_SECRET>
```

## Commands

```text
/start
/cricket
/cricket_cancel
/cricket_stats
/cricket_leaderboard
/cricket_help
```

## Gameplay rules

1. Batter and bowler both choose one number.
2. Choices are hidden until both players pick.
3. If both numbers match, the batter is out.
4. If numbers do not match, batter scores the number they selected.
5. First innings ends when the first batter is out.
6. Second innings starts with a target of first innings score + 1.
7. Second batter wins if they reach the target before getting out.
8. First batter wins if the second batter is out before reaching the target.
9. If the second batter is out on the same score, the match is tied.

## Important note if you already have HCCL ranking commands

This `api/telegram.py` is a complete webhook file. If your current bot already has ranking commands in the same file, copy the cricket sections into your existing file instead of blindly replacing everything, otherwise your older commands may disappear.
