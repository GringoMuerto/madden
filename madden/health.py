"""Two views of the injury report that print under the board. Neither is a price.

Both are display only. They attach no points and touch no pick, no band, no edge and no
tiebreaker, exactly like the exposure section above them. Injuries reach the picks
through the market line: the sheet is frozen Tuesday and the market is not, so when a
starter is ruled out the books move, the sheet does not, and the drift term already
prices that gap. A second injury number on top would double count it.

What they are for is the six or seven games a week picked with a designation still open,
because Scott submits everything Sunday morning by choice. These say which rooms are thin
and which quarterbacks are on the report, so he knows where to look before he submits.

STARTER HEALTH counts listed starters with no row on this week's official report. Healthy
here means the report says nothing, which is a blunt instrument and is labelled as one: a
full-participation note counts against a team exactly like a DNP, and a veteran rest day
counts like an injury. A pointer, not a measurement.

INJURED QUARTERBACKS names every quarterback carrying a row, at his depth-chart rank,
resolved or not. Wider than the exposure section, which names only quarterbacks whose
status is still unresolved: a QB1 at full participation appears here and not there.
"""

from __future__ import annotations

from .injuries import PRACTICE_SHORT

PRACTICE_PHRASE = {
    "Full": "full participation",
    "Limited": "limited in practice",
    "DNP": "did not practice",
}


def health(rep, teams: list) -> list:
    """[(team, off_healthy, off_total, def_healthy, def_total)] in the order given.

    A team with no depth-chart rows returns zero totals and prints as UNKNOWN rather than
    as a clean sheet -- the same rule the exposure section follows.
    """
    rows = []
    for t in teams:
        sides = rep.starters.get(t)
        if not sides:
            rows.append((t, 0, 0, 0, 0))
            continue
        out = []
        for side in ("OFF", "DEF"):
            men = sides.get(side, [])
            listed = sum(1 for _, _, gsis in men if gsis in rep.rows)
            out.append((len(men) - listed, len(men)))
        rows.append((t, out[0][0], out[0][1], out[1][0], out[1][1]))
    return rows


def quarterbacks(rep, teams: list) -> list:
    """[(team, [(label, name, what the report says), ...])], shallowest rank first.

    Rank is a label, never a filter: a QB3 prints alongside a QB1. Without the depth chart
    the rank is unavailable and the label says so, which is what exposure does with the
    same failure.
    """
    out = []
    for t in teams:
        rows = []
        for qb in rep.quarterbacks:
            if qb.team != t:
                continue
            rank = rep.depth.get(qb.gsis_id)
            if rep.depth_error:
                label, order = "QB?", 98
            elif rank is None:
                label, order = "unranked", 99
            else:
                label, order = f"QB{rank}", rank
            status = qb.game_status or "no game status yet"
            practice = PRACTICE_PHRASE.get(
                PRACTICE_SHORT.get(qb.practice_status.lower(), ""), "")
            injury = (rep.rows[qb.gsis_id].injury if qb.gsis_id in rep.rows else qb.injury)
            said = ", ".join(x for x in (status, practice) if x)
            rows.append((order, qb.name, label, said + (f" ({injury})" if injury else "")))
        out.append((t, [(label, name, said) for _, name, label, said in sorted(rows)]))
    return out
