"""
Single Elimination bracket builder.

Generates a standard single-elimination bracket with byes for non-power-of-2 counts.
Returns a list of Match ORM objects (not yet persisted).
"""
import math
from bot.db.models import Match, Player


def build_bracket(tournament_id: int, players: list[Player]) -> list[Match]:
    n = len(players)
    size = 2 ** math.ceil(math.log2(n)) if n > 1 else 2
    matches: list[Match] = []

    # Round 1 slots (size // 2 matches)
    r1_count = size // 2
    r1: list[Match] = []
    for pos in range(r1_count):
        m = Match(tournament_id=tournament_id, round=1, position=pos, bracket="winners")
        # Standard seeding: 1 vs last, 2 vs second-to-last ...
        s1 = pos          # seed index (0-based)
        s2 = size - 1 - pos
        if s1 < n:
            m.player1_id = players[s1].id
        if s2 < n:
            m.player2_id = players[s2].id
        r1.append(m)
        matches.append(m)

    # Build subsequent rounds
    prev_round = r1
    round_num = 2
    while len(prev_round) > 1:
        curr_round: list[Match] = []
        for pos in range(len(prev_round) // 2):
            m = Match(tournament_id=tournament_id, round=round_num, position=pos, bracket="winners")
            curr_round.append(m)
            matches.append(m)
        # Wire next_match links (set after all matches are flushed to get IDs)
        prev_round = curr_round
        round_num += 1

    return matches


def wire_next_matches(matches: list[Match]) -> None:
    """Set next_match_id / next_match_slot after matches are persisted (have IDs)."""
    by_round: dict[int, list[Match]] = {}
    for m in matches:
        by_round.setdefault(m.round, []).append(m)

    rounds = sorted(by_round.keys())
    for i, r in enumerate(rounds[:-1]):
        current = sorted(by_round[r], key=lambda m: m.position)
        next_r = sorted(by_round[rounds[i + 1]], key=lambda m: m.position)
        for j, m in enumerate(current):
            target = next_r[j // 2]
            m.next_match_id = target.id
            m.next_match_slot = (j % 2) + 1  # 1 or 2
