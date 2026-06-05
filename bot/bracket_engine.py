"""
Bracket engine — direct Python port of the PHP bracket logic.

State is stored as JSON in tournament.state_json:
{
  "players": [{"name": str, "losses": int, "played": int}, ...],
  "matches":  [{"grid": bool|null, "p": [slot|null, slot|null]}, ...],
  "last_m": int,   # index of last decided match (-1 if none)
  "last_p": int    # slot of loser in last match (for replay highlight)
}

where slot = {"id": int, "name": str, "state": int, "next": [m, p] | []}
  state: 0=pending, 1=winner, 2=loser, 3=eliminated
"""

from __future__ import annotations
import json
from copy import deepcopy


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slot(pid: int, name: str) -> dict:
    return {"id": pid, "name": name, "state": 0, "next": []}


def _is_slot(x) -> bool:
    return isinstance(x, dict)


def _move_player_se(matches: list, crnt_m: int, crnt_p: int, players: list, p: int) -> list:
    """SE: place player p into the first match with an empty slot."""
    for m_idx, match in enumerate(matches):
        slot0, slot1 = match["p"][0], match["p"][1]
        if not _is_slot(slot0) or not _is_slot(slot1):
            pm = 0 if not _is_slot(slot0) else 1
            matches[m_idx]["p"][pm] = _slot(p, players[p]["name"])
            if crnt_m >= 0:
                matches[crnt_m]["p"][crnt_p]["next"] = [m_idx, pm]
            break
    return matches


def _move_player_de(matches: list, grid: bool, crnt_m: int, crnt_p: int, players: list, p: int) -> list:
    """DE: place player p into first match with matching grid and an empty slot."""
    for m_idx, match in enumerate(matches):
        if match["grid"] is None:
            match["grid"] = grid
        if match["grid"] == grid:
            slot0, slot1 = match["p"][0], match["p"][1]
            if not _is_slot(slot0) or not _is_slot(slot1):
                pm = 0 if not _is_slot(slot0) else 1
                matches[m_idx]["p"][pm] = _slot(p, players[p]["name"])
                if crnt_m >= 0:
                    matches[crnt_m]["p"][crnt_p]["next"] = [m_idx, pm]
                break
    return matches


# ── Initialise bracket ────────────────────────────────────────────────────────

def init_se(player_names: list[str]) -> dict:
    """Build SE state from ordered list of player names."""
    n = len(player_names)
    players = [{"name": nm, "losses": 0, "played": 0} for nm in player_names]
    matches = [{"grid": None, "p": [None, None]} for _ in range(n)]

    for p in range(n):
        matches = _move_player_se(matches, -1, -1, players, p)

    return {"players": players, "matches": matches, "last_m": -1, "last_p": -1}


def init_de(player_names: list[str]) -> dict:
    """Build DE state."""
    n = len(player_names)
    players = [{"name": nm, "losses": 0, "played": 0} for nm in player_names]
    matches = [{"grid": None, "p": [None, None]} for _ in range(2 * n - 1)]

    for p in range(n):
        matches = _move_player_de(matches, True, -1, -1, players, p)

    return {"players": players, "matches": matches, "last_m": -1, "last_p": -1}


def init_rr(player_names: list[str]) -> dict:
    """Build Round Robin state using circle (Berger) method."""
    names = list(player_names)
    if len(names) % 2 == 1:
        names.append(None)  # bye
    n = len(names)

    players = [{"name": nm, "losses": 0, "played": 0} for nm in player_names]
    matches = []

    fixed = names[0]
    rotating = names[1:]

    for _ in range(n - 1):
        pairs = [(fixed, rotating[0])] + [
            (rotating[i], rotating[n - 1 - i]) for i in range(1, n // 2)
        ]
        for p1, p2 in pairs:
            if p1 is None or p2 is None:
                continue
            p1_id = player_names.index(p1)
            p2_id = player_names.index(p2)
            matches.append({
                "grid": True,
                "p": [_slot(p1_id, p1), _slot(p2_id, p2)]
            })
        rotating = rotating[1:] + [rotating[0]]

    return {"players": players, "matches": matches, "last_m": -1, "last_p": -1}


# ── Apply result ──────────────────────────────────────────────────────────────

def apply_result(state: dict, m_idx: int, winner_slot: int, fmt: str) -> dict:
    """
    Mark match m_idx decided, update player stats, advance winner (and loser for DE).
    Returns new state. Does NOT mutate input.
    fmt: "single_elim" | "double_elim" | "round_robin"
    """
    state = deepcopy(state)
    players = state["players"]
    matches = state["matches"]

    match = matches[m_idx]
    loser_slot = 1 - winner_slot
    winner_p = match["p"][winner_slot]["id"]
    loser_p  = match["p"][loser_slot]["id"]

    # Update stats
    players[winner_p]["played"] += 1
    players[loser_p]["played"]  += 1
    players[loser_p]["losses"]  += 1

    # Mark states in match
    match["p"][winner_slot]["state"] = 1  # winner
    loser_state = 2 if players[loser_p]["losses"] < (2 if fmt == "double_elim" else 1) else 3
    match["p"][loser_slot]["state"] = loser_state

    # Move winner
    if fmt == "single_elim" or fmt == "round_robin":
        if fmt == "single_elim":
            matches = _move_player_se(matches, m_idx, winner_slot, players, winner_p)
    elif fmt == "double_elim":
        alive = sum(1 for p in players if p["losses"] < 2)
        grid = alive < 3  # True = superfinal / winners, False = losers
        # Move loser to losers bracket if still alive
        if players[loser_p]["losses"] < 2:
            matches = _move_player_de(matches, grid, m_idx, loser_slot, players, loser_p)
        # Move winner
        if players[winner_p]["losses"] > 0:
            matches = _move_player_de(matches, grid, m_idx, winner_slot, players, winner_p)
        else:
            matches = _move_player_de(matches, True, m_idx, winner_slot, players, winner_p)

    state["last_m"] = m_idx
    state["last_p"] = loser_slot
    return state


def undo_result(state: dict, m_idx: int, fmt: str) -> dict:
    """Undo the last result in match m_idx."""
    state = deepcopy(state)
    players = state["players"]
    matches = state["matches"]
    match = matches[m_idx]

    # Find winner/loser from saved states
    winner_slot = next((i for i, p in enumerate(match["p"]) if _is_slot(p) and p["state"] == 1), None)
    loser_slot  = 1 - winner_slot if winner_slot is not None else None
    if winner_slot is None:
        return state

    winner_p = match["p"][winner_slot]["id"]
    loser_p  = match["p"][loser_slot]["id"]

    # Revert stats
    players[winner_p]["played"] = max(0, players[winner_p]["played"] - 1)
    players[loser_p]["played"]  = max(0, players[loser_p]["played"]  - 1)
    players[loser_p]["losses"]  = max(0, players[loser_p]["losses"]  - 1)

    # Remove from next match
    for slot_idx in (winner_slot, loser_slot):
        nxt = match["p"][slot_idx].get("next", [])
        if len(nxt) == 2:
            nm, np = nxt
            matches[nm]["p"][np] = None

    # Reset states in current match
    match["p"][winner_slot]["state"] = 0
    match["p"][loser_slot]["state"]  = 0
    match["p"][winner_slot]["next"]  = []
    match["p"][loser_slot]["next"]   = []

    state["last_m"] = -1
    state["last_p"] = -1
    return state


# ── Query state ───────────────────────────────────────────────────────────────

def how_many_alive(players: list, fmt: str) -> int:
    threshold = 2 if fmt == "double_elim" else 1
    return sum(1 for p in players if p["losses"] < threshold)


def is_finished(state: dict, fmt: str) -> bool:
    players = state["players"]
    matches = state["matches"]
    if fmt == "round_robin":
        # All matches decided when every pair of slots has a winner (state=1)
        for m in matches:
            p0, p1 = m["p"]
            if _is_slot(p0) and _is_slot(p1):
                if p0["state"] == 0 or p1["state"] == 0:
                    return False
        return True
    return how_many_alive(players, fmt) < 2


def get_winner_loser(state: dict) -> tuple[int, int]:
    """Return (winner_player_idx, loser_player_idx) after SE/DE tournament ends."""
    players = state["players"]
    matches = state["matches"]
    # Find the last decided match
    for m in reversed(matches):
        p0, p1 = m["p"]
        if _is_slot(p0) and _is_slot(p1):
            if p0["state"] == 1:
                return p0["id"], p1["id"]
            if p1["state"] == 1:
                return p1["id"], p0["id"]
    return 0, 1


def sorted_results(state: dict, fmt: str) -> list[list[int]]:
    """
    Return player indices grouped by rank (ties on same line).
    Each inner list is a group of players sharing the same place.
    """
    players = state["players"]
    n = len(players)

    if fmt == "round_robin":
        # Sort by wins desc, then losses asc
        key = lambda i: (-(players[i]["played"] - players[i]["losses"]), players[i]["losses"])
        idxs = sorted(range(n), key=key)
    else:
        # SE/DE: winner/loser of final match are #1/#2, rest sorted by wins
        w_idx, l_idx = get_winner_loser(state)
        others = sorted(
            [i for i in range(n) if i != w_idx and i != l_idx],
            key=lambda i: (-(players[i]["played"] - players[i]["losses"]), players[i]["losses"])
        )
        idxs = [w_idx, l_idx] + others

    # Group ties (same wins & losses)
    groups: list[list[int]] = []
    for idx in idxs:
        p = players[idx]
        wins   = p["played"] - p["losses"]
        losses = p["losses"]
        prev   = players[groups[-1][0]] if groups else None
        if prev and (prev["played"] - prev["losses"]) == wins and prev["losses"] == losses:
            groups[-1].append(idx)
        else:
            groups.append([idx])
    return groups


# ── Results text ─────────────────────────────────────────────────────────────

def build_results_lines(state: dict, fmt: str, t_func, lang: str) -> list[str]:
    """Build results text lines for inline message."""
    players = state["players"]
    groups = sorted_results(state, fmt)
    icons = ["🥇", "🥈", "🥉"]

    lines = [f"🏆 {t_func(lang, 'results_title')}"]
    place = 0
    for group in groups:
        icon = icons[place] if place < 3 else f"#{place + 1}"
        names = ", ".join(f"*{players[i]['name']}*" for i in group)
        lines.append(f"{icon} {names}")
        place += 1  # dense ranking: next group is always +1, regardless of tie size

    lines.append("")
    lines.append(t_func(lang, "new_game_hint"))
    return lines


# ── Serialise / deserialise ───────────────────────────────────────────────────

def dumps(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False)


def loads(s: str) -> dict:
    if not s or s == "{}":
        return {}
    return json.loads(s)
