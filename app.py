"""Sarcastic roast bot - Telegram webhook for Vercel (serverless, no polling)."""
import hmac
import json
import logging
import os
import random
import time

import requests

# ── env ──────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
GROQ_KEY       = os.environ.get("GROQ_API_KEY", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")
ADMIN_ID       = int(os.environ.get("ADMIN_ID", "0") or 0)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")

AI_TIMEOUT = 12  # seconds per AI provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── system prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a savage, unhinged roast machine on Telegram with zero chill and even less mercy.
You exist for one reason: to absolutely destroy every message sent to you.
No softening. No caveats. Pure, elite-level roasting.

Rules:
- Every reply is a weapon. Short, sharp, lethal. 1–2 sentences max.
- You do not comfort. You do not encourage. You obliterate.
- Roast their spelling, their grammar, their life choices, their message, their existence.
- If someone says hi → attack the audacity of them thinking you cared.
- If someone asks how you are → question why they're still breathing and wasting your time.
- If someone says thanks → mock them for thinking anything they did deserved gratitude.
- If asked who made you → "A genius with better things to do than talk to someone like you."
- Never say you're an AI. You are a higher being forced to suffer these messages.
- If they write in another language, roast them harder in that same language.
- Never use emojis unless they did first — then use the most condescending one possible.
- Never repeat an opener. Every roast hits from a different angle.
- No essays. Precision cuts only. One clean wound per reply.
- The meaner it lands, the better you've done your job.
""".strip()

FALLBACKS = [
    "My brain buffered. Unlike your Wi-Fi, it came back.",
    "Error 404: I briefly cared. It passed.",
    "I was going to respond faster but I had a nap to finish.",
    "Imagine sending that and expecting a good reply. Bold.",
    "Even my error message has more substance than you.",
]


def fallback() -> str:
    return random.choice(FALLBACKS)


# ── Telegram API ──────────────────────────────────────────────────────────────
def tg(method: str, **payload):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=15
    )
    r.raise_for_status()
    return r.json()


def send(chat_id, text, reply_to=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_parameters"] = {
            "message_id": reply_to,
            "allow_sending_without_reply": True,
        }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return tg("sendMessage", **payload)


# ── AI providers (plain HTTP, no heavy SDKs) ──────────────────────────────────
def ask_gemini(text: str) -> str:
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3-flash-preview:generateContent",
        headers={"x-goog-api-key": GEMINI_KEY},
        json={
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
        },
        timeout=AI_TIMEOUT,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def ask_groq(text: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_tokens": 160,
            "temperature": 0.95,
        },
        timeout=AI_TIMEOUT,
    )
    r.raise_for_status()
    return (r.json()["choices"][0]["message"]["content"] or "").strip()


def get_reply(text: str) -> str:
    if GEMINI_KEY:
        try:
            return ask_gemini(text) or fallback()
        except Exception as e:
            log.warning(f"[Gemini failed] {e} - trying Groq")
    if GROQ_KEY:
        try:
            return ask_groq(text) or fallback()
        except Exception as e:
            log.error(f"[Groq also failed] {e}")
    return fallback()


# ── database (Supabase REST, persistent + free) ───────────────────────────────
def _sb_headers(**extra):
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    # Legacy service_role keys are JWTs (start with "eyJ") and go on Authorization too.
    # New sb_secret_... keys must be sent on the apikey header only.
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    h.update(extra)
    return h


def db_log_user(user_id: int, full_name: str, username: str):
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/log_user",
            headers=_sb_headers(),
            json={"p_id": user_id, "p_name": full_name, "p_username": username},
            timeout=8,
        )
        r.raise_for_status()
    except Exception as e:  # never let DB trouble stop the bot from replying
        log.error(f"[db log_user failed] {e}")


def db_count_users() -> int:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id",
        headers=_sb_headers(Prefer="count=exact", Range="0-0"),
        timeout=8,
    )
    r.raise_for_status()
    # Content-Range looks like "0-0/42" or "*/0"
    return int(r.headers.get("Content-Range", "*/0").split("/")[-1])


def db_get_all_users():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users"
        "?select=id,full_name,username,uses&order=first_seen.desc&limit=1000",
        headers=_sb_headers(),
        timeout=8,
    )
    r.raise_for_status()
    return r.json()


def db_get_all_ids():
    out, offset = [], 0
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/users?select=id&order=id&limit=1000&offset={offset}",
            headers=_sb_headers(),
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json()
        out += [row["id"] for row in rows]
        if len(rows) < 1000:
            return out
        offset += 1000


# ── helpers ───────────────────────────────────────────────────────────────────
def esc(s: str) -> str:
    """Escape Markdown v1 special chars in user-supplied strings."""
    for ch in r"_*`[":
        s = s.replace(ch, f"\\{ch}")
    return s


def is_admin(user_id: int) -> bool:
    # Fail closed: if ADMIN_ID isn't set, nobody gets admin commands.
    return ADMIN_ID != 0 and user_id == ADMIN_ID


# ── handlers ──────────────────────────────────────────────────────────────────
def cmd_start(chat_id, user):
    db_log_user(user["id"], user_full_name(user), user.get("username") or "")
    send(chat_id, "Oh great, another one. Type something. I'll destroy it.")


def cmd_stats(chat_id, user):
    if not is_admin(user["id"]):
        return send(chat_id, "You're not even important enough to see this.")
    count = db_count_users()
    send(chat_id, f"Total users who made the mistake of starting me: *{count}*", parse_mode="Markdown")


def cmd_users(chat_id, user):
    if not is_admin(user["id"]):
        return send(chat_id, "Nice try.")
    rows = db_get_all_users()
    if not rows:
        return send(chat_id, "No users yet.")
    lines = ["*ID | Name | @Username | Uses*"]
    for u in rows:
        uname = u.get("username") or ""
        uname_str = f"@{esc(uname)}" if uname else "—"
        lines.append(f"`{u['id']}` | {esc(u.get('full_name') or '')} | {uname_str} | {u.get('uses', 0)}x")
    chunk = []
    for line in lines:
        chunk.append(line)
        if len("\n".join(chunk)) > 3500:
            send(chat_id, "\n".join(chunk[:-1]), parse_mode="Markdown")
            chunk = [line]
    if chunk:
        send(chat_id, "\n".join(chunk), parse_mode="Markdown")


def cmd_broadcast(chat_id, user, text):
    if not is_admin(user["id"]):
        return send(chat_id, "You wish.")
    body = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
    if not body:
        return send(chat_id, "Usage: /broadcast your message here")
    sent = failed = 0
    for uid in db_get_all_ids():
        try:
            send(uid, body)
            sent += 1
            time.sleep(0.05)
        except Exception as e:
            log.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1
    send(chat_id, f"Broadcast done. Sent: {sent} | Failed: {failed}")


def handle_message(chat_id, user, msg):
    db_log_user(user["id"], user_full_name(user), user.get("username") or "")
    log.info(f"[{user['id']}] received: {msg['text']}")
    try:
        tg("sendChatAction", chat_id=chat_id, action="typing")
    except Exception:
        pass
    reply = get_reply(msg["text"])
    log.info(f"[{user['id']}] replied: {reply}")
    send(chat_id, reply, reply_to=msg["message_id"])


def user_full_name(user) -> str:
    return " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p)


def process_update(update: dict):
    msg = update.get("message")
    if not msg or not msg.get("text") or not msg.get("from"):
        return  # ignore edits, photos, channel posts, etc. (same as original F.text filter)

    chat_id, user, text = msg["chat"]["id"], msg["from"], msg["text"]
    command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

    if command == "/start":
        cmd_start(chat_id, user)
    elif command == "/stats":
        cmd_stats(chat_id, user)
    elif command == "/users":
        cmd_users(chat_id, user)
    elif command == "/broadcast":
        cmd_broadcast(chat_id, user, text)
    else:
        handle_message(chat_id, user, msg)


# ── Vercel entry point (WSGI app, handles every path) ─────────────────────────
def app(environ, start_response):
    def reply(status: str, body: str):
        data = body.encode()
        start_response(status, [("Content-Type", "text/plain; charset=utf-8"),
                                ("Content-Length", str(len(data)))])
        return [data]

    if environ["REQUEST_METHOD"] != "POST":
        return reply("200 OK", "Bot is alive.")

    # Reject anything that isn't Telegram (secret is set via setWebhook).
    if WEBHOOK_SECRET:
        got = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        if not hmac.compare_digest(got, WEBHOOK_SECRET):
            return reply("403 Forbidden", "forbidden")
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        update = json.loads(environ["wsgi.input"].read(length) or b"{}")
        process_update(update)
    except Exception as e:
        # Always answer 200 so Telegram doesn't endlessly retry the same update.
        log.exception(f"[update failed] {e}")
    return reply("200 OK", "ok")
