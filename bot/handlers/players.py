import random
from aiogram import Router
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, GameState, TournamentFormat, TournamentStatus
from bot.locales.i18n import t
from bot.states import TournamentSetup, TournamentActive
import bot.bracket_engine as eng

router = Router()


@router.message(TournamentSetup.adding_players)
async def handle_player_input(message: Message, session: AsyncSession, state: FSMContext):
    res = await session.execute(select(User).where(User.id == message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    gs_res = await session.execute(select(GameState).where(GameState.user_id == message.chat.id))
    gs = gs_res.scalar_one_or_none()
    if not gs:
        await message.answer(t(lang, "no_active"))
        return

    game_state = eng.loads(gs.state_json)
    players = game_state.get("players", [])
    text = message.text.strip()

    # ── Shuffle ──────────────────────────────────────────────
    if text == t(lang, "btn_shuffle"):
        if players:
            random.shuffle(players)
            game_state["players"] = players
            gs.state_json = eng.dumps(game_state)
            await session.commit()
        from bot.handlers.tournament import _show_player_list
        await _show_player_list(message, gs, lang)
        return

    # ── Cancel ───────────────────────────────────────────────
    if text == t(lang, "btn_cancel"):
        gs.status     = TournamentStatus.IDLE.value
        gs.state_json = "{}"
        await session.commit()
        await state.clear()
        await message.answer(t(lang, "cancelled"), reply_markup=ReplyKeyboardRemove())
        return

    # ── Start tournament ─────────────────────────────────────
    if text == t(lang, "btn_start"):
        if len(players) < 2:
            await message.answer(t(lang, "need_players"))
            return

        names = [p["name"] for p in players]
        fmt   = gs.format

        if fmt == TournamentFormat.SINGLE_ELIM.value:
            bracket = eng.init_se(names)
        elif fmt == TournamentFormat.DOUBLE_ELIM.value:
            bracket = eng.init_de(names)
        else:
            bracket = eng.init_rr(names)

        gs.state_json = eng.dumps(bracket)
        gs.status     = TournamentStatus.ACTIVE.value
        await session.commit()

        await state.set_state(TournamentActive.playing)

        from bot.handlers.matches import send_match_keyboard
        await message.answer(t(lang, "tournament_started"), reply_markup=ReplyKeyboardRemove())
        await send_match_keyboard(message, session, gs, lang)
        return

    # ── Add player ───────────────────────────────────────────
    name = text[:64].strip()
    name = name.replace("'", "").replace('"', "").replace("\\", "").replace("`", "")
    if not name:
        return

    if any(p["name"] == name for p in players):
        await message.answer(t(lang, "player_duplicate", name=name), parse_mode="Markdown")
        return

    players.append({"name": name})
    game_state["players"] = players
    gs.state_json = eng.dumps(game_state)
    await session.commit()

    await message.answer(t(lang, "player_added", name=name), parse_mode="Markdown")
    from bot.handlers.tournament import _show_player_list
    await _show_player_list(message, gs, lang)
