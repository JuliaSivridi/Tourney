from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, GameState, TournamentFormat, TournamentStatus
from bot.locales.i18n import t
from bot.states import TournamentSetup

router = Router()

FORMAT_CALLBACKS = {
    "fmt_se": TournamentFormat.SINGLE_ELIM,
    "fmt_de": TournamentFormat.DOUBLE_ELIM,
    "fmt_rr": TournamentFormat.ROUND_ROBIN,
}


def format_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{t(lang, 'fmt_single_elim')} — {t(lang, 'fmt_single_elim_desc')}",
            callback_data="fmt_se")],
        [InlineKeyboardButton(
            text=f"{t(lang, 'fmt_double_elim')} — {t(lang, 'fmt_double_elim_desc')}",
            callback_data="fmt_de")],
        [InlineKeyboardButton(
            text=f"{t(lang, 'fmt_round_robin')} — {t(lang, 'fmt_round_robin_desc')}",
            callback_data="fmt_rr")],
    ])


def players_keyboard(lang: str, n_players: int) -> InlineKeyboardMarkup:
    rows = []
    if n_players >= 2:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_start"),   callback_data="players:start")])
    if n_players >= 1:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_shuffle"), callback_data="players:shuffle")])
    rows.append(    [InlineKeyboardButton(text=t(lang, "btn_cancel"),  callback_data="players:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def players_text(lang: str, players: list) -> str:
    if not players:
        return t(lang, "add_players")
    player_list = "\n".join(f"{i+1}. {p['name']}" for i, p in enumerate(players))
    return t(lang, "player_list", count=len(players), list=player_list)


async def _get_or_create_state(session: AsyncSession, user_id: int) -> GameState:
    res = await session.execute(select(GameState).where(GameState.user_id == user_id))
    gs = res.scalar_one_or_none()
    if gs is None:
        gs = GameState(user_id=user_id)
        session.add(gs)
        await session.flush()
    return gs


@router.message(Command("newgame"))
async def cmd_newgame(message: Message, session: AsyncSession, state: FSMContext):
    res = await session.execute(select(User).where(User.id == message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    gs = await _get_or_create_state(session, message.chat.id)
    gs.status     = TournamentStatus.IDLE.value
    gs.format     = ""
    gs.title      = ""
    gs.state_json = "{}"
    gs.kbd_message_id = 0
    await session.commit()

    await state.set_state(TournamentSetup.choosing_format)
    await state.update_data(players_msg_id=None)
    await message.answer(t(lang, "new_choose_format"), reply_markup=format_keyboard(lang))


@router.callback_query(TournamentSetup.choosing_format, F.data.in_(FORMAT_CALLBACKS))
async def choose_format(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    res = await session.execute(select(User).where(User.id == cb.message.chat.id))
    user = res.scalar_one_or_none()
    lang = user.lang if user else "en"

    fmt = FORMAT_CALLBACKS[cb.data]
    await cb.message.edit_reply_markup(reply_markup=None)

    gs = await _get_or_create_state(session, cb.message.chat.id)
    gs.format     = fmt.value
    gs.status     = TournamentStatus.SETUP.value
    gs.state_json = "{}"
    await session.commit()

    await state.set_state(TournamentSetup.adding_players)
    await cb.answer()

    msg = await cb.message.answer(
        players_text(lang, []),
        reply_markup=players_keyboard(lang, n_players=0),
        parse_mode="Markdown",
    )
    await state.update_data(players_msg_id=msg.message_id, lang=lang)
