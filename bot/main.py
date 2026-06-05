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

logging.basicConfig(level=logging.INFO)

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type"}


def _json(data) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        headers=CORS,
    )


async def _get_gs(uid_str: str):
    """Return (int_uid, gs) or raise HTTP error."""
    if not uid_str.lstrip("-").isdigit():
        raise web.HTTPBadRequest()
    uid = int(uid_str)
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
    if not gs:
        raise web.HTTPNotFound()
    return uid, gs


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
        # Return empty state so Mini App can show "new tournament" screen
        return _json({"status": "idle", "format": "", "players": [], "matches": []})

    import bot.bracket_engine as eng
    state = eng.loads(gs.state_json)
    return _json({
        "status":  gs.status,
        "format":  gs.format,
        "players": state.get("players", []),
        "matches": state.get("matches", []),
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
        if not gs:
            gs = GameState(user_id=uid)
            session.add(gs)
        gs.format = ""
        gs.title = ""
        gs.status = TournamentStatus.IDLE.value
        gs.kbd_message_id = 0
        gs.state_json = "{}"
        await session.commit()

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
    shuffle = body.get("shuffle", False)

    if not isinstance(player_names, list) or len(player_names) < 2:
        raise web.HTTPBadRequest()

    player_names = [str(n).strip() for n in player_names if str(n).strip()]
    if shuffle:
        random.shuffle(player_names)

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == uid))
        gs = res.scalar_one_or_none()
        if not gs or not gs.format:
            raise web.HTTPNotFound()

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json) or {}
        state["players_pending"] = player_names  # store before bracket is built
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
            return web.HTTPBadRequest(reason="Need at least 2 players")

        if gs.format == "single_elim":
            new_state = eng.init_se(player_names)
        elif gs.format == "double_elim":
            new_state = eng.init_de(player_names)
        else:
            new_state = eng.init_rr(player_names)

        gs.state_json = eng.dumps(new_state)
        gs.status = TournamentStatus.ACTIVE.value
        await session.commit()

        return _json({
            "ok": True,
            "status": gs.status,
            "players": new_state.get("players", []),
            "matches": new_state.get("matches", []),
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

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json)
        state = eng.apply_result(state, m_idx, winner_slot, gs.format)
        gs.state_json = eng.dumps(state)

        finished = eng.is_finished(state, gs.format)
        if finished:
            gs.status = TournamentStatus.FINISHED.value

        await session.commit()

    return _json({
        "ok": True,
        "finished": finished,
        "status": gs.status,
        "players": state.get("players", []),
        "matches": state.get("matches", []),
        "last_m":  state.get("last_m", -1),
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

        import bot.bracket_engine as eng
        state = eng.loads(gs.state_json)
        state = eng.undo_result(state, m_idx, gs.format)
        gs.state_json = eng.dumps(state)
        gs.status = TournamentStatus.ACTIVE.value
        await session.commit()

    return _json({
        "ok": True,
        "players": state.get("players", []),
        "matches": state.get("matches", []),
        "last_m":  state.get("last_m", -1),
    })


# ── OPTIONS (CORS preflight) ──────────────────────────────────────────────────

async def api_options(request: web.Request) -> web.Response:
    return web.Response(headers=CORS)


# ── Static + routing ──────────────────────────────────────────────────────────

async def start_webapp() -> web.AppRunner:
    miniapp_dir = Path(__file__).parent.parent / "docs"

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(miniapp_dir / "index.html")

    app = web.Application()

    # API routes
    app.router.add_get("/api/game/{uid}", api_get)
    app.router.add_post("/api/game/{uid}/new", api_new)
    app.router.add_post("/api/game/{uid}/format", api_set_format)
    app.router.add_post("/api/game/{uid}/players", api_set_players)
    app.router.add_post("/api/game/{uid}/start", api_start)
    app.router.add_post("/api/game/{uid}/match", api_match)
    app.router.add_post("/api/game/{uid}/undo", api_undo)
    app.router.add_route("OPTIONS", "/api/game/{uid}/{tail:.*}", api_options)

    # Static files
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

    webapp_runner = await start_webapp()
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await webapp_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
