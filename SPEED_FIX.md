# Speed fix v1.2

This version answers Telegram callback button taps immediately before doing Supabase updates and Telegram message edits.

What changed:
- Number button spinner stops faster.
- Telegram API calls use a reusable requests session.
- Webhook GET shows v1.2 fast.

Deploy steps:
1. Replace your GitHub files with this version.
2. Commit/push.
3. Redeploy on Vercel.
4. Keep the same environment variables and webhook URL.
