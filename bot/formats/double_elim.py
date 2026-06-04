"""
Double Elimination bracket builder.

Structure:
  - Winners bracket: standard SE bracket
  - Losers bracket: receives losers from winners rounds
  - Grand Final: winners bracket champion vs losers bracket champion
"""
import math
from bot.db.models import Match, Player


def build_bracket(tournament_id: int, players: list[Player]) -> list[Match]:
    n = len(players)
    size = 2 ** math.ceil(math.log2(n)) if n > 1 else 2
    matches: list[Match] = []

    # --- Winners bracket ---
    w_rounds: list[list[Match]] = []
    r1_count = size // 2
    r1: list[Match] = []
    for pos in range(r1_count):
        m = Match(tournament_id=tournament_id, round=1, position=pos, bracket="winners")
        s1, s2 = pos, size - 1 - pos
        if s1 < n:
            m.player1_id = players[s1].id
        if s2 < n:
            m.player2_id = players[s2].id
        r1.append(m)
        matches.append(m)
    w_rounds.append(r1)

    prev = r1
    wr = 2
    while len(prev) > 1:
        curr = [Match(tournament_id=tournament_id, round=wr, position=p, bracket="winners")
                for p in range(len(prev) // 2)]
        for m in curr:
            matches.append(m)
        w_rounds.append(curr)
        prev = curr
        wr += 1

    # --- Losers bracket ---
    # LR1 receives losers from WR1 (r1_count losers -> r1_count//2 matches)
    # subsequent losers rounds alternate: feed round (losers from W) -> elim round
    l_rounds: list[list[Match]] = []
    lr = 1
    incoming_count = r1_count  # losers from WR1

    while incoming_count >= 1:
        # feed round: incoming_count//2 matches (or 1 if incoming_count==1 special)
        feed_count = max(1, incoming_count // 2)
        feed = [Match(tournament_id=tournament_id, round=lr, position=p, bracket="losers")
                for p in range(feed_count)]
        for m in feed:
            matches.append(m)
        l_rounds.append(feed)
        lr += 1

        if feed_count == 1:
            break  # last losers round before grand final

        # elim round
        elim_count = feed_count // 2
        elim = [Match(tournament_id=tournament_id, round=lr, position=p, bracket="losers")
                for p in range(max(1, elim_count))]
        for m in elim:
            matches.append(m)
        l_rounds.append(elim)
        lr += 1

        incoming_count = elim_count

    # --- Grand Final ---
    gf = Match(tournament_id=tournament_id, round=lr, position=0, bracket="final")
    matches.append(gf)

    return matches


def wire_next_matches(matches: list[Match]) -> None:
    winners = sorted([m for m in matches if m.bracket == "winners"], key=lambda m: (m.round, m.position))
    losers = sorted([m for m in matches if m.bracket == "losers"], key=lambda m: (m.round, m.position))
    final = next((m for m in matches if m.bracket == "final"), None)

    # Winners bracket progression
    w_by_round: dict[int, list[Match]] = {}
    for m in winners:
        w_by_round.setdefault(m.round, []).append(m)
    w_rounds = sorted(w_by_round.keys())
    for i, r in enumerate(w_rounds[:-1]):
        curr = sorted(w_by_round[r], key=lambda m: m.position)
        nxt = sorted(w_by_round[w_rounds[i + 1]], key=lambda m: m.position)
        for j, m in enumerate(curr):
            target = nxt[j // 2]
            m.next_match_id = target.id
            m.next_match_slot = (j % 2) + 1

    # Winners champion -> Grand Final slot 1
    if winners and final:
        winners[-1].next_match_id = final.id
        winners[-1].next_match_slot = 1

    # Losers bracket progression
    l_by_round: dict[int, list[Match]] = {}
    for m in losers:
        l_by_round.setdefault(m.round, []).append(m)
    l_rounds = sorted(l_by_round.keys())
    for i, r in enumerate(l_rounds[:-1]):
        curr = sorted(l_by_round[r], key=lambda m: m.position)
        nxt = sorted(l_by_round[l_rounds[i + 1]], key=lambda m: m.position)
        for j, m in enumerate(curr):
            target = nxt[j // 2] if j // 2 < len(nxt) else nxt[-1]
            m.next_match_id = target.id
            m.next_match_slot = (j % 2) + 1

    # Losers champion -> Grand Final slot 2
    if losers and final:
        losers[-1].next_match_id = final.id
        losers[-1].next_match_slot = 2
