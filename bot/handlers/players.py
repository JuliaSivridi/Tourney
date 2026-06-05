import random
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, GameState, TournamentFormat, TournamentStatus
from bot.locales.i18n import t
from bot.states import TournamentSetup, TournamentActive
import bot.bracket_engine as eng

log = logging.getLogger(__name__)
router = Router()


async def _edit_players_msg(bot, chat_id: int, msg_id: int, lang: str, players: list):
    """Edit the player-list message in place."""
    from bot.handlers.tournament import players_text, players_keyboard
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=players_text(lang, players),
            reply_markup=players_keyboard(lang, has_players=bool(players)),
            parse_mode="Markdown",
        )
    except Exception as e:
        log.debug("edit players msg skipped: %s", e)


# ── User types a player name ──────────────────────────────────────────────────

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

    name = message.text.strip()[:64]
    name = name.replace("'", "").replace('"', "").replace("\\", "").replace("`", "").strip()
    if not name:
        return

    game_state = eng.loads(gs.state_json)
    players = game_state.get("players", [])

    # Duplicate — silently ignore
    if any(p["name"] == name for p in players):
        return

    players.append({"name": name})
    game_state["players"] = players
    gs.state_json = eng.dumps(game_state)
    await session.commit()

    data = await state.get_data()
    msg_id = data.get("players_msg_id")
    if msg_id:
        await _edit_players_msg(message.bot, message.chat.id, msg_id, lang, players)


# ── Inline button callbacks ───────────────────────────────────────────────────

@router.callback_query(TournamentSetup.adding_players, F.data == "players:shuffle")
async def cb_shuffle(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await cb.answer()
    res = await session.execute(select(User).where(User.id == cb.message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    gs_res = await session.execute(select(GameState).where(GameState.user_id == cb.message.chat.id))
    gs = gs_res.scalar_one_or_none()
    if not gs:
        return

    game_state = eng.loads(gs.state_json)
    players = game_state.get("players", [])
    if players:
        random.shuffle(players)
        game_state["players"] = players
        gs.state_json = eng.dumps(game_state)
        await session.commit()

    data = await state.get_data()
    msg_id = data.get("players_msg_id")
    if msg_id:
        await _edit_players_msg(cb.bot, cb.message.chat.id, msg_id, lang, players)


@router.callback_query(TournamentSetup.adding_players, F.data == "players:cancel")
async def cb_cancel(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await cb.answer()
    res = await session.execute(select(User).where(User.id == cb.message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    gs_res = await session.execute(select(GameState).where(GameState.user_id == cb.message.chat.id))
    gs = gs_res.scalar_one_or_none()
    if gs:
        gs.status     = TournamentStatus.IDLE.value
        gs.state_json = "{}"
        await session.commit()

    await state.clear()
    await cb.message.edit_text(t(lang, "cancelled"), reply_markup=None)


@router.callback_query(TournamentSetup.adding_players, F.data == "players:start")
async def cb_start(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await cb.answer()
    res = await session.execute(select(User).where(User.id == cb.message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    gs_res = await session.execute(select(GameState).where(GameState.user_id == cb.message.chat.id))
    gs = gs_res.scalar_one_or_none()
    if not gs:
        return

    game_state = eng.loads(gs.state_json)
    players = game_state.get("players", [])

    if len(players) < 2:
        await cb.answer(t(lang, "need_players"), show_alert=True)
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

    # Remove buttons from player list message
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    from bot.handlers.matches import send_match_keyboard
    await cb.message.answer(t(lang, "tournament_started"))
    await send_match_keyboard(cb.message, session, gs, lang)
