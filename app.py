import hmac
import os
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.telegram import handle_message, handle_callback

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

app = FastAPI()


def secret_valid(request: Request) -> bool:
    """Validate Telegram secret token from header, with query fallback for browser testing."""
    if not WEBHOOK_SECRET:
        return True
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    query_secret = request.query_params.get("secret") or ""
    return hmac.compare_digest(header_secret, WEBHOOK_SECRET) or hmac.compare_digest(query_secret, WEBHOOK_SECRET)


@app.get("/")
@app.get("/api/telegram")
async def health_check():
    return JSONResponse({
        "ok": True,
        "service": "HCCL Telegram Cricket Bot Webhook",
        "path": "/api/telegram",
        "message": "POST Telegram updates to this endpoint.",
    })


@app.post("/api/telegram")
async def telegram_webhook(request: Request):
    if not secret_valid(request):
        return JSONResponse({"ok": False, "error": "invalid webhook secret"}, status_code=401)

    try:
        update = await request.json()

        if "message" in update:
            handle_message(update["message"])
        elif "callback_query" in update:
            handle_callback(update["callback_query"])

        return JSONResponse({"ok": True})
    except Exception as exc:
        # Return 200 so Telegram does not endlessly retry a broken update.
        print("Webhook error:", repr(exc))
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=200)
