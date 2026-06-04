from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, GameState, TournamentStatus
from bot.locales.i18n import t, normalize_lang, flags_keyboard, lang_from_flag_btn

router = Router()


async def get_or_create_user(session: AsyncSession, message: Message) -> User:
    chat_id = message.chat.id
    result = await session.execute(select(User).where(User.id == chat_id))
    user = result.scalar_one_or_none()
    if user is None:
        lang = normalize_lang(message.from_user.language_code or "en")
        name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name]))
        user = User(id=chat_id, user_name=name, lang=lang)
        session.add(user)
        # Create empty game state row
        session.add(GameState(user_id=chat_id))
        await session.commit()
    return user


async def get_lang(session: AsyncSession, chat_id: int) -> str:
    res = await session.execute(select(User.lang).where(User.id == chat_id))
    lang = res.scalar_one_or_none()
    return lang if lang else "en"


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message)
    await message.answer(t(user.lang, "hi", name=message.from_user.first_name))


@router.message(Command("help"))
async def cmd_help(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message)
    await message.answer(t(user.lang, "help"))


@router.message(Command("lang"))
async def cmd_lang(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message)
    btns = [[KeyboardButton(text=b)] for b in flags_keyboard()]
    kb = ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True, one_time_keyboard=True)
    await message.answer(t(user.lang, "lang_ask"), reply_markup=kb)


@router.message(lambda m: lang_from_flag_btn(m.text or "") is not None)
async def set_lang(message: Message, session: AsyncSession):
    lang = lang_from_flag_btn(message.text)
    res = await session.execute(select(User).where(User.id == message.chat.id))
    user = res.scalar_one_or_none()
    if user:
        user.lang = lang
        await session.commit()
    await message.answer(t(lang, "lang_ok"), reply_markup=ReplyKeyboardRemove())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    lang = await get_lang(session, message.chat.id)
    await message.answer(t(lang, "cancelled"), reply_markup=ReplyKeyboardRemove())
