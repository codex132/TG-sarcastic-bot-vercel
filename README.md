# Sarcastic bot - Vercel webhook version

## 1. Database (free Supabase)
1. supabase.com -> New project.
2. SQL Editor -> paste `supabase.sql` -> Run.
3. Project Settings -> API: copy the **Project URL** and the **service_role** key.

## 2. Deploy
1. Push this folder to a GitHub repo.
2. vercel.com -> Add New -> Project -> pick the repo -> before deploying, add these Environment Variables:
   `BOT_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `ADMIN_ID`, `WEBHOOK_SECRET`, `SUPABASE_URL`, `SUPABASE_KEY`
   (`WEBHOOK_SECRET` = any random string using only letters, numbers, `_` and `-`)
3. Deploy.

## 3. Connect Telegram (once, from any browser)
```
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<your-project>.vercel.app/api/webhook&secret_token=<WEBHOOK_SECRET>
```
You should see `"Webhook was set"`. Check anytime with `/getWebhookInfo`.

## Notes
- Visiting `https://<your-project>.vercel.app/api/webhook` should show "Bot is alive."
- Stop the Railway bot first, otherwise polling and webhook conflict.
- If you change the Vercel URL, run setWebhook again.
- `/stats`, `/users`, `/broadcast` only work when `ADMIN_ID` is set to your Telegram ID.
