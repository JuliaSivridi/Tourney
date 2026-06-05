import logging
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, GameState, TournamentStatus
from bot.locales.i18n import t
from bot.config import WEBAPP_URL
import bot.bracket_engine as eng

log = logging.getLogger(__name__)
router = Router()


# ── Inline keyboard from bracket state ───────────────────────────────────────

_STATE_ICON = {0: "⚪", 1: "🟢", 2: "🔴", 3: "⚫"}


def build_keyboard(state: dict, user_id: int, lang: str) -> InlineKeyboardMarkup:
    """
    One row per match — exactly like the PHP version:
      [🟩#01]  [⚪ Alice]  [⚪ Bob]
    Completed matches stay visible with 🟢/🔴/⚫ icons (no clickable action).
    """
    matches  = state.get("matches", [])
    last_m   = state.get("last_m", -1)
    last_p_l = state.get("last_p", -1)
    rows = []

    for m_idx, match in enumerate(matches):
        p0, p1 = match["p"][0], match["p"][1]
        if not eng._is_slot(p0) or not eng._is_slot(p1):
            continue  # future match — slots not filled yet

        grid = match.get("grid", True)
        grid_icon = "🟩" if grid else "🟥"
        already_decided = p0["state"] != 0 and p1["state"] != 0

        # Callback for each player button
        def cb(slot: int, player) -> str:
            # Replay check FIRST — must come before already_decided
            if m_idx == last_m and slot == last_p_l:
                return f"m:{m_idx}:{slot}:replay"  # undo last result
            if already_decided:
                return f"m:{m_idx}:x"              # decided, no action
            if player["state"] == 0:
                return f"m:{m_idx}:{slot}:pick"    # pick winner
            return f"m:{m_idx}:x"

        rows.append([
            InlineKeyboardButton(
                text=f"{grid_icon}#{m_idx:02d}",
                callback_data=f"m:{m_idx}:x",
            ),
            InlineKeyboardButton(
                text=f"{_STATE_ICON[p0['state']]} {p0['name']}",
                callback_data=cb(0, p0),
            ),
            InlineKeyboardButton(
                text=f"{_STATE_ICON[p1['state']]} {p1['name']}",
                callback_data=cb(1, p1),
            ),
        ])

    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(
            text=t(lang, "btn_bracket"),
            web_app=WebAppInfo(url=f"{WEBAPP_URL}?uid={user_id}"),
        )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Send keyboard after tournament start ──────────────────────────────────────

async def send_match_keyboard(
    message: Message,
    session: AsyncSession,
    gs: GameState,
    lang: str,
) -> None:
    state = eng.loads(gs.state_json)
    kb = build_keyboard(state, gs.user_id, lang)
    msg = await message.answer(t(lang, "matches_header"), reply_markup=kb)
    gs.kbd_message_id = msg.message_id
    await session.commit()


# ── Handle button press ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("m:"))
async def handle_match_pick(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    try:
        parts = cb.data.split(":")
        # "m:{idx}:x"  — header button, ignore
        # "m:{idx}:{slot}:{action}"  — player button
        if len(parts) < 4 or parts[2] == "x":
            return

        m_idx       = int(parts[1])
        winner_slot = int(parts[2])
        action      = parts[3]  # "pick" | "replay"

        gs_res = await session.execute(
            select(GameState).where(GameState.user_id == cb.message.chat.id)
        )
        gs = gs_res.scalar_one_or_none()
        if not gs or gs.status != TournamentStatus.ACTIVE.value:
            log.warning("No active game for user %s", cb.message.chat.id)
            return

        user_res = await session.execute(select(User).where(User.id == cb.message.chat.id))
        user = user_res.scalar_one_or_none()
        lang = user.lang if user else "en"

        state = eng.loads(gs.state_json)
        fmt   = gs.format

        if action == "replay":
            # Undo only — do NOT apply a new result
            state = eng.undo_result(state, m_idx, fmt)
            gs.state_json = eng.dumps(state)
            await session.commit()
            kb = build_keyboard(state, gs.user_id, lang)
            try:
                await cb.message.edit_text(t(lang, "matches_header"), reply_markup=kb)
            except Exception:
                pass
            return

        state = eng.apply_result(state, m_idx, winner_slot, fmt)
        gs.state_json = eng.dumps(state)
        await session.commit()

        winner_name = state["matches"][m_idx]["p"][winner_slot]["name"]

        if eng.is_finished(state, fmt):
            await _show_results(cb.message, session, gs, state, lang)
            return

        kb = build_keyboard(state, gs.user_id, lang)
        try:
            await cb.message.edit_text(
                t(lang, "win_msg", winner=winner_name, match=m_idx),
                reply_markup=kb,
            )
        except Exception:
            msg = await cb.message.answer(
                t(lang, "win_msg", winner=winner_name, match=m_idx),
                reply_markup=kb,
            )
            gs.kbd_message_id = msg.message_id
            await session.commit()

    except Exception as e:
        log.exception("handle_match_pick error: %s", e)
        try:
            await cb.message.answer(f"⚠️ Error: {e}")
        except Exception:
            pass


# ── Final results ─────────────────────────────────────────────────────────────

async def _show_results(
    message,
    session: AsyncSession,
    gs: GameState,
    state: dict,
    lang: str,
):
    gs.status = TournamentStatus.FINISHED.value
    await session.commit()

    players = state["players"]
    w_idx, l_idx = eng.get_winner_loser(state)

    lines = [f"🏆 {t(lang, 'results_title')}"]
    lines.append(f"🥇 *{players[w_idx]['name']}*")
    lines.append(f"🥈 *{players[l_idx]['name']}*")

    seen = {w_idx, l_idx}
    by_played: dict[int, list[str]] = {}
    for i, p in enumerate(players):
        if i not in seen:
            by_played.setdefault(p.get("played", 0), []).append(p["name"])

    place = 3
    for cnt in sorted(by_played.keys(), reverse=True):
        icon = "🥉" if place == 3 else f"#{place}"
        lines.append(icon + " " + ", ".join(f"_{n}_" for n in by_played[cnt]))
        place += len(by_played[cnt])

    # Keep the keyboard message (shows match history) — just update text without buttons
    kb = build_keyboard(state, gs.user_id, lang)
    try:
        await message.edit_text(t(lang, "matches_header"), reply_markup=kb)
    except Exception:
        pass

    # Send results as a separate message
    await message.answer("\n".join(lines), parse_mode="Markdown")
