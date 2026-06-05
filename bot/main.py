import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from bot.config import BOT_TOKEN, WEBAPP_PORT
from bot.db.engine import init_db, AsyncSessionLocal
from bot.db.models import GameState
from bot.middleware import DbSessionMiddleware
from bot.handlers import start, tournament, players, matches

logging.basicConfig(level=logging.INFO)


async def api_game(request: web.Request) -> web.Response:
    uid = request.match_info["uid"]
    if not uid.lstrip("-").isdigit():
        raise web.HTTPBadRequest()

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(GameState).where(GameState.user_id == int(uid)))
        gs = res.scalar_one_or_none()
        if not gs:
            raise web.HTTPNotFound()

    import bot.bracket_engine as eng
    state = eng.loads(gs.state_json)

    data = {
        "title":   gs.title,
        "format":  gs.format,
        "status":  gs.status,
        "players": state.get("players", []),
        "matches": state.get("matches", []),
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def start_webapp() -> web.AppRunner:
    miniapp_dir = Path(__file__).parent.parent / "docs"
    app = web.Application()
    app.router.add_get("/api/game/{uid}", api_game)
    app.router.add_static("/", miniapp_dir, show_index=True)
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
