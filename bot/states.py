from aiogram.fsm.state import State, StatesGroup


class TournamentSetup(StatesGroup):
    choosing_format = State()
    adding_players  = State()


class TournamentActive(StatesGroup):
    playing = State()
