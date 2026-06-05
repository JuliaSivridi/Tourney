import asyncio
import json
import logging
import random
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from bot.config import BOT_TOKEN, WEBAPP_PORT
from bot.db.engine import init_db, AsyncSessionLocal
from bot.db.models import GameState, User, TournamentStatus
from bot.middleware import DbSessionMiddleware
from bot.handlers import start, tournament, players, matches
from bot.locales.i18n import t

logging.basicConfig(level=logging.INFO)

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type"}


def _json(data) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        headers=CORS,
    )


# ── Round computation ─────────────────────────────────────────────────────────

def _assign_rounds(match_list: list, fmt: str, n_players: int) -> list[dict]:
    """Return matches with added 'round' and 'section' fields."""
    result = []

    if fmt == "single_elim":
        round_map = {}
        idx, r, rem = 0, 1, n_players
        while rem > 1:
            cnt = rem // 2
            for i in range(cnt):
                round_map[idx + i] = r
            idx += cnt
            rem = cnt
            r += 1
        for i, m in enumerate(match_list):
            result.append({**m, "round": round_map.get(i, r - 1), "section": "winners"})

    elif fmt == "double_elim":
        # grid=True  → winners bracket
        # grid=False → losers bracket
        # grid=None  → grand final / not yet assigned
        true_idx  = [i for i, m in enumerate(match_list) if m.get("grid") is True]
        false_idx = [i for i, m in enumerate(match_list) if m.get("grid") is False]

        # Winners: SE-like round assignment
        w_round = {}
        idx, r, rem = 0, 1, n_players
        while rem > 1:
            cnt = rem // 2
            for j in range(cnt):
                if idx + j < len(true_idx):
                    w_round[true_idx[idx + j]] = r
            idx += cnt
            rem = cnt
            r += 1
        # Remaining winners matches (odd bracket, etc.) — sequential rounds
        for ti in true_idx:
            if ti not in w_round:
                w_round[ti] = r
                r += 1
        max_w_round = max(w_round.values(), default=1)

        # Losers bracket: pairs of indices share a round
        l_round = {}
        for j, li in enumerate(false_idx):
            l_round[li] = j // 2 + 1

        # Grand final (grid=None): comes after all winners rounds
        gf_round = max_w_round + 1

        for i, m in enumerate(match_list):
            if m.get("grid") is False:
                result.append({**m, "round": l_round.get(i, 1), "section": "losers"})
            elif m.get("grid") is None:
                result.append({**m, "round": gf_round, "section": "winners"})
            else:
                result.append({**m, "round": w_round.get(i, max_w_round), "section": "winners"})

    elif fmt == "round_robin":
        # Distribute into rounds: n/2 matches per round (round robin rule)
        n = n_players if n_players % 2 == 0 else n_players - 1
        mpr = max(n // 2, 1)
        for i, m in enumerate(match_list):
            result.append({**m, "round": i // mpr + 1, "section": "rr"})

    else:
        for i, m in enumerate(match_list):
            result.append({**m, "round": 1, "section": "winners"})

    return result


# ── Inline keyboard sync ──────────────────────────────────────────────────────

async def _sync_inline(app: web.Application, uid: int, gs, state: dict, lang: str, text: str | None = None):
    """Update the inline keyboard message in Telegram after a web action."""
    if not gs.kbd_message_id:
        return
    try:
        from bot.handlers.matches import build_keyboard
        from bot.locales.i18n import t
        bot: Bot = app["bot"]
        kb = build_keyboard(state, uid, lang)
        await bot.edit_message_text(
            chat_id=uid,
            message_id=gs.kbd_message_id,
            text=text or t(lang, "matches_header"),
            reply_markup=kb,
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.debug("Inline sync skipped: %s", e)


async def _sync_inline_finished(app: web.Application, uid: int, gs, state: dict, lang: str):
    """Send tournament results to Telegram when finished via web."""
    if not gs.kbd_message_id:
        return
    try:
        from bot.handlers.matches import build_keyboard
        from bot.locales.i18n import t
        import bot.bracket_engine as eng
        bot: Bot = app["bot"]

        # Edit keyboard message — remove webapp button, preserve current text
        kb = build_keyboard(state, uid, lang, show_webapp=False)
        try:
            await bot.edit_message_reply_markup(
                chat_id=uid,
                message_id=gs.kbd_message_id,
                reply_markup=kb,
            )
        except Exception:
            pass

        # Build results text
        lines = eng.build_results_lines(state, gs.format, t, lang)

        await bot.send_message(
            chat_id=uid,
            text="\n".join(lines),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.debug("Inline finished sync skipped: %s", e)


# ── GET /api/game/{uid} ───────────────────────────────────────────────────────

async def api_get(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()

    if not gs:
        return _json({"status": "idle", "format": "", "players": [], "matches": []})

    import bot.bracket_engine as eng
    state = eng.loads(gs.state_json)
    raw_matches = state.get("matches", [])
    n_players = len(state.get("players", []))

    enriched = _assign_rounds(raw_matches, gs.format, n_players) if gs.format else raw_matches

    return _json({
        "status":  gs.status,
        "format":  gs.format,
        "players": state.get("players", []),
        "matches": enriched,
        "last_m":  state.get("last_m", -1),
    })


# ── POST /api/game/{uid}/new ──────────────────────────────────────────────────

async def api_new(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        old_kbd_id = gs.kbd_message_id if gs else 0
        old_state_json = gs.state_json if gs else "{}"

        if not gs:
            gs = GameState(user_id=uid)
            session.add(gs)
        gs.format = ""
        gs.title = ""
        gs.status = TournamentStatus.IDLE.value
        gs.kbd_message_id = 0
        gs.state_json = "{}"
        await session.commit()

    # Remove webapp button from old keyboard message
    if old_kbd_id:
        try:
            from bot.handlers.matches import build_keyboard
            import bot.bracket_engine as eng
            bot_inst: Bot = request.app["bot"]
            old_state = eng.loads(old_state_json)
            kb = build_keyboard(old_state, uid, "ru", show_webapp=False)
            await bot_inst.edit_message_reply_markup(
                chat_id=uid,
                message_id=old_kbd_id,
                reply_markup=kb,
            )
        except Exception as e:
            logging.debug("api_new keyboard cleanup skipped: %s", e)

    return _json({"ok": True})


# ── POST /api/game/{uid}/format ───────────────────────────────────────────────

async def api_set_format(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)
    body = await request.json()
    fmt = body.get("format", "")
    if fmt not in ("single_elim", "double_elim", "round_robin"):
        raise web.HTTPBadRequest()

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs:
            raise web.HTTPNotFound()
        gs.format = fmt
        gs.status = TournamentStatus.IDLE.value
        gs.state_json = "{}"
        await session.commit()

    return _json({"ok": True})


# ── POST /api/game/{uid}/players ──────────────────────────────────────────────

async def api_set_players(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)
    body = await request.json()
    player_names = body.get("players", [])
    if not isinstance(player_names, list) or len(player_names) < 2:
        raise web.HTTPBadRequest()

    player_names = [str(n).strip() for n in player_names if str(n).strip()]

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs or not gs.format:
            raise web.HTTPNotFound()

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json) or {}
        state["players_pending"] = player_names
        gs.state_json = eng.dumps(state)
        await session.commit()

    return _json({"ok": True, "players": player_names})


# ── POST /api/game/{uid}/start ────────────────────────────────────────────────

async def api_start(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs or not gs.format:
            raise web.HTTPNotFound()

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json) or {}
        player_names = state.get("players_pending", [])
        if len(player_names) < 2:
            raise web.HTTPBadRequest(reason="Need at least 2 players")

        if gs.format == "single_elim":
            new_state = eng.init_se(player_names)
        elif gs.format == "double_elim":
            new_state = eng.init_de(player_names)
        else:
            new_state = eng.init_rr(player_names)

        gs.state_json = eng.dumps(new_state)
        gs.status = TournamentStatus.ACTIVE.value
        await session.commit()

    raw_matches = new_state.get("matches", [])
    enriched = _assign_rounds(raw_matches, gs.format, len(player_names))
    return _json({
        "ok": True,
        "format": gs.format,
        "status": gs.status,
        "players": new_state.get("players", []),
        "matches": enriched,
        "last_m": -1,
    })


# ── POST /api/game/{uid}/match ────────────────────────────────────────────────

async def api_match(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)
    body = await request.json()
    m_idx = body.get("m_idx")
    winner_slot = body.get("winner_slot")
    if m_idx is None or winner_slot not in (0, 1):
        raise web.HTTPBadRequest()

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs or gs.status != TournamentStatus.ACTIVE.value:
            raise web.HTTPNotFound()

        user_res = await session.execute(select(User).where(User.id == uid))
        user = user_res.scalar_one_or_none()
        lang = user.lang if user else "ru"

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json)
        match = state.get("matches", [])[m_idx] if m_idx < len(state.get("matches", [])) else None
        if not match or not eng._is_slot(match["p"][0]) or not eng._is_slot(match["p"][1]):
            return _json({"ok": False, "error": "match not ready"})
        state = eng.apply_result(state, m_idx, winner_slot, gs.format)
        gs.state_json = eng.dumps(state)

        finished = eng.is_finished(state, gs.format)
        if finished:
            gs.status = TournamentStatus.FINISHED.value

        await session.commit()

    # Sync to inline keyboard
    if finished:
        await _sync_inline_finished(request.app, uid, gs, state, lang)
    else:
        winner_name = state["matches"][m_idx]["p"][winner_slot]["name"]
        win_text = t(lang, "win_msg", winner=winner_name, match=m_idx)
        await _sync_inline(request.app, uid, gs, state, lang, text=win_text)

    raw_matches = state.get("matches", [])
    n_players = len(state.get("players", []))
    enriched = _assign_rounds(raw_matches, gs.format, n_players)

    return _json({
        "ok": True,
        "format": gs.format,
        "finished": finished,
        "status": gs.status,
        "players": state.get("players", []),
        "matches": enriched,
        "last_m": state.get("last_m", -1),
    })


# ── POST /api/game/{uid}/undo ─────────────────────────────────────────────────

async def api_undo(request: web.Request) -> web.Response:
    uid_str = request.match_info["uid"]
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)
    body = await request.json()
    m_idx = body.get("m_idx")
    if m_idx is None:
        raise web.HTTPBadRequest()

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs:
            raise web.HTTPNotFound()

        user_res = await session.execute(select(User).where(User.id == uid))
        user = user_res.scalar_one_or_none()
        lang = user.lang if user else "ru"

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json)
        state = eng.undo_result(state, m_idx, gs.format)
        gs.state_json = eng.dumps(state)
        gs.status = TournamentStatus.ACTIVE.value
        await session.commit()

    await _sync_inline(request.app, uid, gs, state, lang)

    raw_matches = state.get("matches", [])
    n_players = len(state.get("players", []))
    enriched = _assign_rounds(raw_matches, gs.format, n_players)

    return _json({
        "ok": True,
        "format": gs.format,
        "players": state.get("players", []),
        "matches": enriched,
        "last_m": state.get("last_m", -1),
    })


# ── OPTIONS (CORS preflight) ──────────────────────────────────────────────────

async def api_options(request: web.Request) -> web.Response:
    return web.Response(headers=CORS)


# ── Static + routing ──────────────────────────────────────────────────────────

async def start_webapp(bot: Bot) -> web.AppRunner:
    miniapp_dir = Path(__file__).parent.parent / "docs"

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(miniapp_dir / "index.html")

    app = web.Application()
    app["bot"] = bot

    app.router.add_get("/api/game/{uid}", api_get)
    app.router.add_post("/api/game/{uid}/new", api_new)
    app.router.add_post("/api/game/{uid}/format", api_set_format)
    app.router.add_post("/api/game/{uid}/players", api_set_players)
    app.router.add_post("/api/game/{uid}/start", api_start)
    app.router.add_post("/api/game/{uid}/match", api_match)
    app.router.add_post("/api/game/{uid}/undo", api_undo)
    app.router.add_route("OPTIONS", "/api/game/{uid}/{tail:.*}", api_options)

    app.router.add_get("/", index)
    app.router.add_static("/", miniapp_dir, show_index=False)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBAPP_PORT)
    await site.start()
    logging.info("Mini App + API on port %s", WEBAPP_PORT)
    return runner


async def main():
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    dp.include_router(start.router)
    dp.include_router(tournament.router)
    dp.include_router(players.router)
    dp.include_router(matches.router)

    webapp_runner = await start_webapp(bot)
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await webapp_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
