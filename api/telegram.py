import json
import os
import random
import hmac
import html
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from supabase import create_client


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

PLAYERS_TABLE = "hccl_cricket_players"
GAMES_TABLE = "hccl_cricket_games"
BALLS_TABLE = "hccl_cricket_balls"

MODE_LABELS = {
    "normal": "Default",
    "one_three": "1-3 Mode",
    "no_five": "No 5 Mode",
}

MODE_NUMBERS = {
    "normal": [1, 2, 3, 4, 5, 6],
    "one_three": [1, 2, 3],
    "no_five": [1, 2, 3, 4, 0, 6],
}

_supabase = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sb():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variable.")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def tg(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    response = requests.post(url, json=payload, timeout=10)
    try:
        return response.json()
    except Exception:
        return {"ok": False, "status_code": response.status_code, "text": response.text}


def send_message(chat_id, text: str, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg("sendMessage", payload)


def edit_message(chat_id, message_id, text: str, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg("editMessageText", payload)


def answer_callback(callback_query_id, text: str = "", show_alert: bool = False):
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text:
        payload["text"] = text[:200]
    return tg("answerCallbackQuery", payload)


def safe_name_from_player(player: dict | None, fallback_id=None) -> str:
    if not player:
        return html.escape(str(fallback_id or "Unknown"))
    username = player.get("username")
    first_name = player.get("first_name")
    last_name = player.get("last_name")
    if username:
        return "@" + html.escape(username)
    name = " ".join(x for x in [first_name, last_name] if x)
    return html.escape(name or str(player.get("telegram_id") or fallback_id or "Unknown"))


def get_player(telegram_id: int):
    res = sb().table(PLAYERS_TABLE).select("*").eq("telegram_id", int(telegram_id)).limit(1).execute()
    return res.data[0] if res.data else None


def get_player_name(telegram_id: int) -> str:
    return safe_name_from_player(get_player(telegram_id), telegram_id)


def is_registered(telegram_id: int) -> bool:
    return get_player(telegram_id) is not None


def register_player(user: dict):
    data = {
        "telegram_id": int(user["id"]),
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "updated_at": now_iso(),
    }
    sb().table(PLAYERS_TABLE).upsert(data, on_conflict="telegram_id").execute()
    return data


def update_player_stats(telegram_id: int, *, games=0, wins=0, losses=0, draws=0, runs=0, wickets=0):
    player = get_player(telegram_id)
    if not player:
        return
    updates = {
        "games_played": int(player.get("games_played") or 0) + games,
        "wins": int(player.get("wins") or 0) + wins,
        "losses": int(player.get("losses") or 0) + losses,
        "draws": int(player.get("draws") or 0) + draws,
        "total_runs": int(player.get("total_runs") or 0) + runs,
        "total_wickets": int(player.get("total_wickets") or 0) + wickets,
        "updated_at": now_iso(),
    }
    sb().table(PLAYERS_TABLE).update(updates).eq("telegram_id", int(telegram_id)).execute()


def cb(game_id: str, *parts: str) -> str:
    return "|".join(["ck", game_id, *parts])


def btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def waiting_keyboard(game_id: str, selected_mode: str) -> dict:
    def label(mode: str) -> str:
        prefix = "✅ " if mode == selected_mode else ""
        return prefix + MODE_LABELS[mode]

    return keyboard([
        [btn("🏏 Join Game", cb(game_id, "join"))],
        [
            btn(label("normal"), cb(game_id, "mode", "normal")),
            btn(label("one_three"), cb(game_id, "mode", "one_three")),
        ],
        [btn(label("no_five"), cb(game_id, "mode", "no_five"))],
    ])


def bat_bowl_keyboard(game_id: str) -> dict:
    return keyboard([
        [btn("🏏 Bat", cb(game_id, "bat")), btn("🎯 Bowl", cb(game_id, "bowl"))]
    ])


def play_keyboard(game_id: str, mode: str) -> dict:
    nums = MODE_NUMBERS.get(mode, MODE_NUMBERS["normal"])
    row = [btn(str(n), cb(game_id, "pick", str(n))) for n in nums]
    if len(row) <= 3:
        return keyboard([row])
    return keyboard([row[:3], row[3:]])


def get_game(game_id: str):
    res = sb().table(GAMES_TABLE).select("*").eq("id", game_id).limit(1).execute()
    return res.data[0] if res.data else None


def update_game(game_id: str, updates: dict):
    updates = {**updates, "updated_at": now_iso()}
    res = sb().table(GAMES_TABLE).update(updates).eq("id", game_id).select("*").execute()
    return res.data[0] if res.data else get_game(game_id)


def get_active_game_for_chat(chat_id: int):
    res = (
        sb().table(GAMES_TABLE)
        .select("*")
        .eq("chat_id", int(chat_id))
        .neq("status", "finished")
        .neq("status", "cancelled")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def waiting_text(game: dict) -> str:
    creator = get_player_name(game["creator_id"])
    mode = MODE_LABELS.get(game.get("mode"), "Default")
    return (
        "🏏 <b>HCCL Hand Cricket</b>\n\n"
        f"Challenge by: <b>{creator}</b>\n"
        f"Mode: <b>{html.escape(mode)}</b>\n\n"
        "Another registered player can tap <b>Join Game</b> to play.\n"
        "Creator can change the mode before someone joins."
    )


def toss_text(game: dict) -> str:
    creator = get_player_name(game["creator_id"])
    opponent = get_player_name(game["opponent_id"])
    toss_winner = get_player_name(game["toss_winner_id"])
    mode = MODE_LABELS.get(game.get("mode"), "Default")
    return (
        "🏏 <b>HCCL Hand Cricket</b>\n\n"
        f"Players: <b>{creator}</b> vs <b>{opponent}</b>\n"
        f"Mode: <b>{html.escape(mode)}</b>\n\n"
        f"🪙 Toss winner: <b>{toss_winner}</b>\n"
        "Toss winner, choose whether to bat or bowl."
    )


def choice_status(game: dict) -> str:
    batter_locked = game.get("batter_choice") is not None
    bowler_locked = game.get("bowler_choice") is not None
    if batter_locked and bowler_locked:
        return "Both players locked. Revealing result..."
    if batter_locked:
        return "✅ Batter locked. Bowler, pick your number."
    if bowler_locked:
        return "✅ Bowler locked. Batter, pick your number."
    return "Both players pick secretly using the buttons below."


def play_text(game: dict, prefix: str = "") -> str:
    batter = get_player_name(game["batter_id"])
    bowler = get_player_name(game["bowler_id"])
    mode = MODE_LABELS.get(game.get("mode"), "Default")
    innings = int(game.get("innings") or 1)
    score = int(game.get("current_score") or 0)
    balls = int(game.get("balls") or 0)

    target_line = ""
    if innings == 2:
        target_line = f"\nTarget: <b>{int(game.get('target') or 0)}</b>"

    body = (
        "🏏 <b>HCCL Hand Cricket</b>\n\n"
        f"Mode: <b>{html.escape(mode)}</b>\n"
        f"Innings: <b>{innings}</b>{target_line}\n"
        f"Batter: <b>{batter}</b>\n"
        f"Bowler: <b>{bowler}</b>\n"
        f"Score: <b>{score}</b>\n"
        f"Balls: <b>{balls}</b>\n\n"
        f"{choice_status(game)}"
    )
    return (prefix + "\n\n" + body).strip() if prefix else body


def reveal_text(game: dict, batter_pick: int, bowler_pick: int, runs: int, is_out: bool, total: int) -> str:
    batter = get_player_name(game["batter_id"])
    bowler = get_player_name(game["bowler_id"])
    if is_out:
        result = "💥 <b>OUT!</b>"
    else:
        result = f"✅ <b>{runs} run{'s' if runs != 1 else ''}</b> added."
    return (
        "🎲 <b>Ball Result</b>\n"
        f"Batter {batter}: <b>{batter_pick}</b>\n"
        f"Bowler {bowler}: <b>{bowler_pick}</b>\n"
        f"{result}\n"
        f"Total: <b>{total}</b>"
    )


def insert_ball(game: dict, batter_pick: int, bowler_pick: int, runs: int, is_out: bool, total: int, ball_no: int):
    sb().table(BALLS_TABLE).insert({
        "game_id": game["id"],
        "chat_id": int(game["chat_id"]),
        "innings": int(game.get("innings") or 1),
        "ball_no": int(ball_no),
        "batter_id": int(game["batter_id"]),
        "bowler_id": int(game["bowler_id"]),
        "batter_pick": int(batter_pick),
        "bowler_pick": int(bowler_pick),
        "runs": int(runs),
        "is_out": bool(is_out),
        "total_after": int(total),
    }).execute()


def apply_final_stats(game: dict):
    if game.get("stats_applied"):
        return

    first_batter = int(game["first_batter_id"])
    first_bowler = int(game["first_bowler_id"])
    second_batter = first_bowler
    second_bowler = first_batter

    s1 = int(game.get("innings1_score") or 0)
    s2 = int(game.get("innings2_score") or 0)
    winner_id = game.get("winner_id")

    first_wickets = 1 if game.get("innings1_out") else 0
    second_wickets = 1 if game.get("innings2_out") else 0

    if winner_id is None:
        update_player_stats(first_batter, games=1, draws=1, runs=s1, wickets=second_wickets)
        update_player_stats(second_batter, games=1, draws=1, runs=s2, wickets=first_wickets)
    else:
        winner_id = int(winner_id)
        loser_id = second_batter if winner_id == first_batter else first_batter
        update_player_stats(
            first_batter,
            games=1,
            wins=1 if winner_id == first_batter else 0,
            losses=1 if loser_id == first_batter else 0,
            runs=s1,
            wickets=second_wickets,
        )
        update_player_stats(
            second_batter,
            games=1,
            wins=1 if winner_id == second_batter else 0,
            losses=1 if loser_id == second_batter else 0,
            runs=s2,
            wickets=first_wickets,
        )

    update_game(game["id"], {"stats_applied": True})


def final_text(game: dict, prefix: str = "") -> str:
    first_batter = int(game["first_batter_id"])
    second_batter = int(game["first_bowler_id"])
    first_name = get_player_name(first_batter)
    second_name = get_player_name(second_batter)
    s1 = int(game.get("innings1_score") or 0)
    s2 = int(game.get("innings2_score") or 0)
    winner_id = game.get("winner_id")

    if winner_id is None:
        result = "🤝 <b>Match tied!</b>"
    else:
        winner = get_player_name(int(winner_id))
        if int(winner_id) == second_batter:
            margin = f"won by chasing the target."
        else:
            margin_runs = max(0, s1 - s2)
            margin = f"won by {margin_runs} run{'s' if margin_runs != 1 else ''}."
        result = f"🏆 Winner: <b>{winner}</b> — {margin}"

    body = (
        "🏁 <b>Match Finished</b>\n\n"
        f"1st Innings — <b>{first_name}</b>: <b>{s1}</b>\n"
        f"2nd Innings — <b>{second_name}</b>: <b>{s2}</b>\n\n"
        f"{result}\n\n"
        "Start another match with /cricket"
    )
    return (prefix + "\n\n" + body).strip() if prefix else body


def finish_game(game: dict, final_score: int, ended_by_out: bool, prefix: str):
    first_score = int(game.get("innings1_score") or 0)
    second_batter = int(game["batter_id"])
    first_batter = int(game["first_batter_id"])

    if final_score > first_score:
        winner_id = second_batter
    elif final_score < first_score:
        winner_id = first_batter
    else:
        winner_id = None

    updates = {
        "status": "finished",
        "innings2_score": int(final_score),
        "innings2_out": bool(ended_by_out),
        "current_score": int(final_score),
        "batter_choice": None,
        "bowler_choice": None,
        "winner_id": winner_id,
        "finished_at": now_iso(),
    }
    updated = update_game(game["id"], updates)
    apply_final_stats(updated)
    updated = get_game(game["id"])
    return final_text(updated, prefix), None


def process_ball(game: dict):
    batter_pick = int(game["batter_choice"])
    bowler_pick = int(game["bowler_choice"])
    is_out = batter_pick == bowler_pick
    runs = 0 if is_out else batter_pick
    total = int(game.get("current_score") or 0) + runs
    ball_no = int(game.get("balls") or 0) + 1

    insert_ball(game, batter_pick, bowler_pick, runs, is_out, total, ball_no)
    reveal = reveal_text(game, batter_pick, bowler_pick, runs, is_out, total)

    innings = int(game.get("innings") or 1)
    if innings == 1:
        if is_out:
            updates = {
                "innings": 2,
                "innings1_score": total,
                "innings1_out": True,
                "target": total + 1,
                "current_score": 0,
                "balls": 0,
                "batter_id": int(game["bowler_id"]),
                "bowler_id": int(game["batter_id"]),
                "batter_choice": None,
                "bowler_choice": None,
            }
            updated = update_game(game["id"], updates)
            prefix = reveal + "\n\n🔁 <b>Innings changed.</b> Target is <b>{}</b>.".format(total + 1)
            return play_text(updated, prefix), play_keyboard(updated["id"], updated["mode"])

        updated = update_game(game["id"], {
            "current_score": total,
            "balls": ball_no,
            "batter_choice": None,
            "bowler_choice": None,
        })
        return play_text(updated, reveal), play_keyboard(updated["id"], updated["mode"])

    # Second innings
    target = int(game.get("target") or 0)
    if not is_out and total >= target:
        return finish_game(game, total, ended_by_out=False, prefix=reveal)

    if is_out:
        return finish_game(game, total, ended_by_out=True, prefix=reveal)

    updated = update_game(game["id"], {
        "current_score": total,
        "balls": ball_no,
        "batter_choice": None,
        "bowler_choice": None,
    })
    return play_text(updated, reveal), play_keyboard(updated["id"], updated["mode"])


def create_game(chat_id: int, creator_id: int):
    active = get_active_game_for_chat(chat_id)
    if active:
        return None, active

    game_id = str(uuid.uuid4())
    game = {
        "id": game_id,
        "chat_id": int(chat_id),
        "creator_id": int(creator_id),
        "mode": "normal",
        "status": "waiting",
    }
    sb().table(GAMES_TABLE).insert(game).execute()
    game = get_game(game_id)
    sent = send_message(chat_id, waiting_text(game), waiting_keyboard(game_id, "normal"))
    message_id = sent.get("result", {}).get("message_id") if sent else None
    if message_id:
        game = update_game(game_id, {"message_id": int(message_id)})
    return game, None


def start_game_from_message(message: dict):
    chat = message["chat"]
    user = message["from"]
    chat_id = int(chat["id"])
    chat_type = chat.get("type")

    if chat_type == "private":
        send_message(chat_id, "🏏 You are registered if you used /start. Send /cricket inside your group to start a match.")
        return

    if not is_registered(int(user["id"])):
        send_message(chat_id, "Please register first by opening this bot privately and pressing /start.")
        return

    game, active = create_game(chat_id, int(user["id"]))
    if active:
        send_message(chat_id, "A cricket match is already active in this group. Use /cricket_cancel to cancel it, or finish the current match first.")


def cancel_game_from_message(message: dict):
    chat_id = int(message["chat"]["id"])
    user_id = int(message["from"]["id"])
    game = get_active_game_for_chat(chat_id)
    if not game:
        send_message(chat_id, "No active cricket match found in this group.")
        return
    player_ids = {int(game["creator_id"])}
    if game.get("opponent_id"):
        player_ids.add(int(game["opponent_id"]))
    if user_id not in player_ids:
        send_message(chat_id, "Only one of the current players can cancel this match.")
        return
    updated = update_game(game["id"], {"status": "cancelled", "finished_at": now_iso()})
    text = "❌ <b>Cricket match cancelled.</b>\n\nStart another match with /cricket"
    if updated.get("message_id"):
        edit_message(chat_id, updated["message_id"], text)
    else:
        send_message(chat_id, text)


def send_help(chat_id: int):
    text = (
        "🏏 <b>HCCL Hand Cricket Bot</b>\n\n"
        "<b>Commands</b>\n"
        "/start — register yourself\n"
        "/cricket — start a group challenge\n"
        "/cricket_cancel — cancel the active match\n"
        "/cricket_stats — see your stats\n"
        "/cricket_leaderboard — see top players\n\n"
        "<b>Rules</b>\n"
        "Batter and bowler secretly pick a number. If both numbers match, batter is out. "
        "If they do not match, batter scores the number they picked. First innings ends on out, second player chases the target."
    )
    send_message(chat_id, text)


def send_stats(chat_id: int, user_id: int):
    player = get_player(user_id)
    if not player:
        send_message(chat_id, "Please register first with /start.")
        return
    name = safe_name_from_player(player, user_id)
    games = int(player.get("games_played") or 0)
    wins = int(player.get("wins") or 0)
    losses = int(player.get("losses") or 0)
    draws = int(player.get("draws") or 0)
    runs = int(player.get("total_runs") or 0)
    wickets = int(player.get("total_wickets") or 0)
    win_rate = (wins / games * 100) if games else 0
    text = (
        f"📊 <b>Cricket Stats — {name}</b>\n\n"
        f"Games: <b>{games}</b>\n"
        f"Wins: <b>{wins}</b>\n"
        f"Losses: <b>{losses}</b>\n"
        f"Draws: <b>{draws}</b>\n"
        f"Win Rate: <b>{win_rate:.1f}%</b>\n"
        f"Total Runs: <b>{runs}</b>\n"
        f"Total Wickets: <b>{wickets}</b>"
    )
    send_message(chat_id, text)


def send_leaderboard(chat_id: int):
    res = sb().table(PLAYERS_TABLE).select("*").limit(100).execute()
    players = res.data or []
    players.sort(key=lambda p: (int(p.get("wins") or 0), int(p.get("total_runs") or 0), -int(p.get("losses") or 0)), reverse=True)
    top = players[:10]
    if not top:
        send_message(chat_id, "No registered cricket players yet. Use /start to register.")
        return

    lines = ["🏆 <b>HCCL Cricket Leaderboard</b>", ""]
    for i, p in enumerate(top, start=1):
        name = safe_name_from_player(p, p.get("telegram_id"))
        wins = int(p.get("wins") or 0)
        losses = int(p.get("losses") or 0)
        draws = int(p.get("draws") or 0)
        runs = int(p.get("total_runs") or 0)
        lines.append(f"{i}. <b>{name}</b> — W:{wins} L:{losses} D:{draws} Runs:{runs}")
    send_message(chat_id, "\n".join(lines))


def command_from_text(text: str) -> str:
    if not text:
        return ""
    first = text.strip().split()[0].lower()
    return first.split("@")[0]


def handle_message(message: dict):
    text = message.get("text") or ""
    user = message.get("from")
    chat = message.get("chat")
    if not user or not chat:
        return

    chat_id = int(chat["id"])
    user_id = int(user["id"])
    cmd = command_from_text(text)

    if cmd == "/start":
        register_player(user)
        send_message(
            chat_id,
            "✅ You are registered for HCCL Hand Cricket.\n\nAdd me to your group and send /cricket to start a match."
        )
        return

    if cmd in ["/help", "/cricket_help"]:
        send_help(chat_id)
        return

    if cmd == "/cricket":
        start_game_from_message(message)
        return

    if cmd == "/cricket_cancel":
        cancel_game_from_message(message)
        return

    if cmd in ["/cricket_stats", "/mystats"]:
        send_stats(chat_id, user_id)
        return

    if cmd in ["/cricket_leaderboard", "/cricket_top"]:
        send_leaderboard(chat_id)
        return


def handle_mode_callback(callback: dict, game: dict, mode: str):
    cqid = callback["id"]
    user_id = int(callback["from"]["id"])
    if user_id != int(game["creator_id"]):
        answer_callback(cqid, "Only the challenge creator can change the mode.", True)
        return
    if game.get("status") != "waiting":
        answer_callback(cqid, "Mode can only be changed before someone joins.", True)
        return
    if mode not in MODE_LABELS:
        answer_callback(cqid, "Unknown mode.", True)
        return
    updated = update_game(game["id"], {"mode": mode})
    edit_message(updated["chat_id"], updated["message_id"], waiting_text(updated), waiting_keyboard(updated["id"], mode))
    answer_callback(cqid, f"Mode set to {MODE_LABELS[mode]}.")


def handle_join_callback(callback: dict, game: dict):
    cqid = callback["id"]
    user = callback["from"]
    user_id = int(user["id"])

    if game.get("status") != "waiting":
        answer_callback(cqid, "This game is not open for joining.", True)
        return
    if user_id == int(game["creator_id"]):
        answer_callback(cqid, "You cannot join your own challenge.", True)
        return
    if not is_registered(user_id):
        answer_callback(cqid, "Register first by opening the bot privately and pressing /start.", True)
        return

    toss_winner_id = random.choice([int(game["creator_id"]), user_id])
    updated = update_game(game["id"], {
        "opponent_id": user_id,
        "status": "toss",
        "toss_winner_id": toss_winner_id,
    })
    edit_message(updated["chat_id"], updated["message_id"], toss_text(updated), bat_bowl_keyboard(updated["id"]))
    answer_callback(cqid, "Joined the match!")


def handle_bat_bowl_callback(callback: dict, game: dict, choice: str):
    cqid = callback["id"]
    user_id = int(callback["from"]["id"])
    if game.get("status") != "toss":
        answer_callback(cqid, "Bat/Bowl selection is not active.", True)
        return
    if user_id != int(game["toss_winner_id"]):
        answer_callback(cqid, "Only the toss winner can choose bat or bowl.", True)
        return

    creator_id = int(game["creator_id"])
    opponent_id = int(game["opponent_id"])
    other_id = opponent_id if user_id == creator_id else creator_id

    if choice == "bat":
        batter_id = user_id
        bowler_id = other_id
    else:
        bowler_id = user_id
        batter_id = other_id

    updated = update_game(game["id"], {
        "status": "playing",
        "innings": 1,
        "batter_id": batter_id,
        "bowler_id": bowler_id,
        "first_batter_id": batter_id,
        "first_bowler_id": bowler_id,
        "current_score": 0,
        "balls": 0,
        "batter_choice": None,
        "bowler_choice": None,
    })
    prefix = f"🪙 Toss winner chose to <b>{choice}</b>. Match started!"
    edit_message(updated["chat_id"], updated["message_id"], play_text(updated, prefix), play_keyboard(updated["id"], updated["mode"]))
    answer_callback(cqid, "Match started!")


def handle_pick_callback(callback: dict, game: dict, pick_text: str):
    cqid = callback["id"]
    user_id = int(callback["from"]["id"])

    if game.get("status") != "playing":
        answer_callback(cqid, "This match is not active.", True)
        return

    try:
        pick = int(pick_text)
    except ValueError:
        answer_callback(cqid, "Invalid pick.", True)
        return

    allowed = MODE_NUMBERS.get(game.get("mode"), MODE_NUMBERS["normal"])
    if pick not in allowed:
        answer_callback(cqid, "This number is not available in the selected mode.", True)
        return

    if user_id == int(game["batter_id"]):
        field = "batter_choice"
        role = "Batter"
    elif user_id == int(game["bowler_id"]):
        field = "bowler_choice"
        role = "Bowler"
    else:
        answer_callback(cqid, "Only the current batter and bowler can play this ball.", True)
        return

    if game.get(field) is not None:
        answer_callback(cqid, f"{role}, you already picked for this ball.", True)
        return

    updated = update_game(game["id"], {field: pick})
    if updated.get("batter_choice") is not None and updated.get("bowler_choice") is not None:
        text, markup = process_ball(updated)
        fresh = get_game(game["id"])
        edit_message(fresh["chat_id"], fresh["message_id"], text, markup)
        answer_callback(cqid, "Pick locked. Result revealed.")
        return

    edit_message(updated["chat_id"], updated["message_id"], play_text(updated), play_keyboard(updated["id"], updated["mode"]))
    answer_callback(cqid, f"{role} pick locked.")


def handle_callback(callback: dict):
    data = callback.get("data") or ""
    cqid = callback.get("id")
    parts = data.split("|")
    if len(parts) < 3 or parts[0] != "ck":
        if cqid:
            answer_callback(cqid, "Unknown button.", True)
        return

    game_id = parts[1]
    action = parts[2]
    game = get_game(game_id)
    if not game:
        answer_callback(cqid, "Game not found.", True)
        return

    if action == "mode" and len(parts) >= 4:
        handle_mode_callback(callback, game, parts[3])
    elif action == "join":
        handle_join_callback(callback, game)
    elif action in ["bat", "bowl"]:
        handle_bat_bowl_callback(callback, game, action)
    elif action == "pick" and len(parts) >= 4:
        handle_pick_callback(callback, game, parts[3])
    else:
        answer_callback(cqid, "Unknown action.", True)


class handler(BaseHTTPRequestHandler):
    def _json_response(self, status_code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _secret_valid(self) -> bool:
        if not WEBHOOK_SECRET:
            return True
        header_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
        query_secret = parse_qs(urlparse(self.path).query).get("secret", [""])[0]
        return hmac.compare_digest(header_secret, WEBHOOK_SECRET) or hmac.compare_digest(query_secret, WEBHOOK_SECRET)

    def do_GET(self):
        self._json_response(200, {
            "ok": True,
            "service": "HCCL Telegram Cricket Bot Webhook",
            "path": "/api/telegram",
            "message": "POST Telegram updates to this endpoint.",
        })

    def do_POST(self):
        if not self._secret_valid():
            self._json_response(401, {"ok": False, "error": "invalid webhook secret"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            update = json.loads(raw.decode("utf-8")) if raw else {}

            if "message" in update:
                handle_message(update["message"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])

            self._json_response(200, {"ok": True})
        except Exception as exc:
            # Return 200 so Telegram does not endlessly retry broken updates.
            print("Webhook error:", repr(exc))
            self._json_response(200, {"ok": False, "error": str(exc)})
