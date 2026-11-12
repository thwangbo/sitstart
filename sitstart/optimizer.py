"""Best legal lineup from projected points, respecting locks.

Interim version: ranks on Sleeper projections in your league's scoring. Step 3
replaces the value with the blended score (projections + expert consensus).

Rules:
- A starter whose game has kicked off stays in his slot; a locked bench player can't come in.
- Slots are filled most-restrictive first (QB/RB/WR/TE, then FLEX, then SUPER_FLEX).
  With nested eligibility like Sleeper's, this greedy order gives the optimal lineup.
- In multi-position slots, a player within 0.5 pts of the best but kicking off later is
  preferred, keeping late swaps possible if an early starter gets hurt.
"""

from __future__ import annotations

from .sleeper import OUT_STATUSES, SLOT_ELIGIBILITY, can_fill

TIE_POINTS = 0.5
QUESTIONABLE_FACTOR = 0.85  # haircut for Questionable players until Sunday inactives post


def can_play(card: dict) -> bool:
    return not (card.get("bye") or card.get("injury_status") in OUT_STATUSES or not card.get("team"))


def _value(card: dict) -> float:
    """Projected points, discounted if Questionable; anyone who can't play ranks below every active player."""
    if not can_play(card):
        return -1.0
    v = card.get("score") if isinstance(card.get("score"), (int, float)) else card.get("proj_pts")
    v = float(v) if isinstance(v, (int, float)) else 0.0
    if card.get("injury_status") == "Questionable":
        v *= QUESTIONABLE_FACTOR
    return v


def _swap_ok(rows: list[dict], i: int, j: int) -> bool:
    a, b = rows[i], rows[j]
    if a["locked"] or b["locked"] or not a["player"] or not b["player"]:
        return False
    return can_fill(a["slot"], b["player"]) and can_fill(b["slot"], a["player"])


def _stabilize(rows: list[dict], current: list[dict]) -> None:
    """Same players, fewer moves: put each kept player back in his current slot when legal."""
    changed = True
    while changed:
        changed = False
        for i, cur in enumerate(current):
            p = cur["player"]
            if not p or not rows[i]["player"] or rows[i]["player"]["player_id"] == p["player_id"]:
                continue
            j = next((k for k, r in enumerate(rows) if r["player"] and r["player"]["player_id"] == p["player_id"]), None)
            if j is not None and _swap_ok(rows, i, j):
                rows[i]["player"], rows[j]["player"] = rows[j]["player"], rows[i]["player"]
                changed = True


def _late_into_flex(rows: list[dict]) -> None:
    """Zero-cost swap: a multi-position slot should hold the later kickoff."""
    for i, r in enumerate(rows):
        if len(SLOT_ELIGIBILITY.get(r["slot"], ())) <= 1:
            continue
        for j, s in enumerate(rows):
            if i == j or not _swap_ok(rows, i, j):
                continue
            ki, kj = rows[i]["player"].get("kickoff_utc") or "", rows[j]["player"].get("kickoff_utc") or ""
            if kj > ki and len(SLOT_ELIGIBILITY.get(s["slot"], ())) < len(SLOT_ELIGIBILITY.get(r["slot"], ())):
                rows[i]["player"], rows[j]["player"] = rows[j]["player"], rows[i]["player"]


def best_lineup(lineup: list[dict], bench: list[dict]) -> list[dict]:
    """lineup: rows from lineup_from_starters. bench: bench player cards (no IR/taxi).
    Returns rows in slot order: {"slot", "player", "locked"}."""
    result: list[dict | None] = [None] * len(lineup)
    pool: list[dict] = []
    for i, row in enumerate(lineup):
        p = row["player"]
        if row.get("locked") and p:
            result[i] = {"slot": row["slot"], "player": p, "locked": True}
        elif p:
            pool.append(p)
    pool += [c for c in bench if not c.get("locked")]

    open_idx = [i for i, r in enumerate(result) if r is None]
    open_idx.sort(key=lambda i: (len(SLOT_ELIGIBILITY.get(lineup[i]["slot"], ())) or 9, i))

    used: set[str] = set()
    for i in open_idx:
        slot = lineup[i]["slot"]
        eligible = [c for c in pool if c["player_id"] not in used and can_fill(slot, c)]
        if not eligible:
            result[i] = {"slot": slot, "player": None, "locked": False}
            continue
        top = max(_value(c) for c in eligible)
        if len(SLOT_ELIGIBILITY.get(slot, ())) > 1:
            near = [c for c in eligible if top - _value(c) <= TIE_POINTS]
            pick = max(near, key=lambda c: (c.get("kickoff_utc") or "", _value(c)))
        else:
            pick = max(eligible, key=_value)
        used.add(pick["player_id"])
        result[i] = {"slot": slot, "player": pick, "locked": False}
    rows: list[dict] = result  # type: ignore[assignment]
    _stabilize(rows, lineup)
    _late_into_flex(rows)
    return rows


def suggested_changes(lineup: list[dict], best: list[dict]) -> dict:
    """Who comes in, who goes out, and the projected gain."""
    cur_ids = {r["player"]["player_id"]: r["player"] for r in lineup if r["player"]}
    new_ids = {r["player"]["player_id"]: r["player"] for r in best if r["player"]}
    ins = sorted((new_ids[k] for k in new_ids.keys() - cur_ids.keys()), key=lambda c: -_value(c))
    outs = sorted((cur_ids[k] for k in cur_ids.keys() - new_ids.keys()), key=lambda c: _value(c))
    cur_total = sum(max(_value(r["player"]), 0.0) for r in lineup if r["player"])
    new_total = sum(max(_value(r["player"]), 0.0) for r in best if r["player"])
    moved = [(r["slot"], r["player"]["name"]) for r, b in zip(lineup, best)
             if r["player"] and b["player"] and r["player"]["player_id"] != b["player"]["player_id"]
             and r["player"]["player_id"] in new_ids]
    def brief(c: dict) -> dict:
        raw = c.get("score") if isinstance(c.get("score"), (int, float)) else c.get("proj_pts")
        raw = raw if isinstance(raw, (int, float)) else 0.0
        return {"player_id": c["player_id"], "name": c["name"], "proj_pts": round(raw, 1),
                "value": round(max(_value(c), 0.0), 1), "injury_status": c.get("injury_status")}

    empties_now = sum(1 for r in lineup if not r["player"])
    empties_best = sum(1 for r in best if not r["player"])
    actionable = bool(ins) and (new_total - cur_total > 0.05
                                or any(not can_play(c) for c in outs)
                                or empties_best < empties_now)
    return {
        "actionable": actionable,
        "start": [brief(c) for c in ins],
        "sit": [brief(c) for c in outs],
        "slot_moves": moved,
        "current_total": round(cur_total, 1),
        "best_total": round(new_total, 1),
        "gain": round(new_total - cur_total, 1),
        "lineup": [{"slot": r["slot"], "player_id": r["player"]["player_id"] if r["player"] else None,
                    "name": r["player"]["name"] if r["player"] else None, "locked": r["locked"]} for r in best],
    }
