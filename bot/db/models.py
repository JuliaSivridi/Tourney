from sqlalchemy import BigInteger, Integer, String, Text, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    pass


class TournamentFormat(str, enum.Enum):
    SINGLE_ELIM  = "single_elim"
    DOUBLE_ELIM  = "double_elim"
    ROUND_ROBIN  = "round_robin"


class TournamentStatus(str, enum.Enum):
    IDLE     = "idle"      # no active game
    SETUP    = "setup"     # collecting players
    ACTIVE   = "active"    # matches in progress
    FINISHED = "finished"  # game over


class User(Base):
    """One row per Telegram user. Stores language preference."""
    __tablename__ = "users"

    id:        Mapped[int] = mapped_column(BigInteger, primary_key=True)  # chat_id
    user_name: Mapped[str] = mapped_column(String(256), nullable=False)
    lang:      Mapped[str] = mapped_column(String(8), default="en")


class GameState(Base):
    """
    One row per user — exactly like the PHP version.
    Stores the entire tournament state as JSON.
    /newgame resets this row; no separate tournament/player/match tables needed.
    """
    __tablename__ = "game_state"

    user_id:        Mapped[int] = mapped_column(BigInteger, primary_key=True)
    format:         Mapped[str] = mapped_column(String(32), default="")
    title:          Mapped[str] = mapped_column(String(256), default="")
    status:         Mapped[str] = mapped_column(String(16), default=TournamentStatus.IDLE.value)
    kbd_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    state_json:     Mapped[str] = mapped_column(Text, default="{}")
