"""
Round Robin bracket builder using the circle method (berger tables).
Generates all pairings; each pair plays exactly once.
"""
from bot.db.models import Match, Player


def build_bracket(tournament_id: int, players: list[Player]) -> list[Match]:
    names = list(players)
    # Add a bye if odd number of players
    if len(names) % 2 == 1:
        names.append(None)  # type: ignore[arg-type]

    n = len(names)
    rounds = n - 1
    matches: list[Match] = []

    fixed = names[0]
    rotating = names[1:]

    for r in range(rounds):
        pairs = [(fixed, rotating[0])]
        for i in range(1, n // 2):
            pairs.append((rotating[i], rotating[n - 1 - i]))

        pos = 0
        for p1, p2 in pairs:
            if p1 is None or p2 is None:
                # bye — skip
                rotating = rotating[1:] + [rotating[0]]
                continue
            m = Match(
                tournament_id=tournament_id,
                round=r + 1,
                position=pos,
                bracket="winners",
                player1_id=p1.id,
                player2_id=p2.id,
            )
            matches.append(m)
            pos += 1

        # rotate
        rotating = rotating[1:] + [rotating[0]]

    return matches


def wire_next_matches(matches: list[Match]) -> None:
    # Round Robin has no progression — all matches are independent
    pass
