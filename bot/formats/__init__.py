from bot.db.models import TournamentFormat
from bot.formats import single_elim, double_elim, round_robin

_BUILDERS = {
    TournamentFormat.SINGLE_ELIM: single_elim,
    TournamentFormat.DOUBLE_ELIM: double_elim,
    TournamentFormat.ROUND_ROBIN: round_robin,
}


def build_bracket(fmt: TournamentFormat, tournament_id: int, players):
    return _BUILDERS[fmt].build_bracket(tournament_id, players)


def wire_next_matches(fmt: TournamentFormat, matches):
    return _BUILDERS[fmt].wire_next_matches(matches)
