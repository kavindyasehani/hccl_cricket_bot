# Vercel deployment fix

This version includes a root `app.py` FastAPI entrypoint.

Vercel now looks for a supported Python entrypoint such as `app.py`, `index.py`, `server.py`, `main.py`, etc. The webhook route remains:

`/api/telegram`

Use this webhook URL:

`https://YOUR-VERCEL-URL.vercel.app/api/telegram`
