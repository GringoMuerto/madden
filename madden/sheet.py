"""Parse the pool operator's weekly pick'em sheet.

The operator edits his own template, so day blocks resize week to week. The header row is
located by finding the labels, never by hardcoding a row number. A game count that does not
match the expected slate is a HARD STOP (sheet fault is the only halting condition).

The ALL CAPS convention marks the nominal home team. It is used as a CROSS CHECK only.
Venue comes from the schedule. For international games the operator capitalises a team that
is not at home, so neutral sites must be declared in the week file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

from .teams import abbr

DAY_WORDS = ("wednesday", "thursday", "friday", "saturday", "sunday", "monday", "tuesday")
_DAY_RE = re.compile(r"\b(" + "|".join(DAY_WORDS) + r")\b", re.I)


class SheetFault(Exception):
    """The sheet will not parse or does not match the slate. Madden halts."""


@dataclass
class Game:
    favorite: str            # abbreviation
    underdog: str
    spread: float            # always positive, as the operator prints it
    day: str                 # "Sunday", "Monday", ...
    nominal_home: str        # whichever side was in ALL CAPS on the sheet
    row: int
    neutral_site: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def home(self) -> str:
        return self.nominal_home

    @property
    def away(self) -> str:
        return self.underdog if self.nominal_home == self.favorite else self.favorite

    @property
    def sheet_home_line(self) -> float:
        """Points the home team is favored by on the frozen sheet. Negative if a home dog."""
        return self.spread if self.nominal_home == self.favorite else -self.spread

    def __str__(self) -> str:
        return f"{self.away} at {self.home} ({self.favorite} -{self.spread})"


def _is_allcaps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _cell(row, idx):
    if idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


HEADER_LABELS = ("favorite", "spread", "underdog")


@dataclass
class Header:
    row: int
    favorite: int            # column indices
    spread: int
    underdog: int


def find_header(rows) -> Header | None:
    """Locate the Favorite / Spread / Underdog header row, or None if there is none.

    By label, never by row number: the operator edits his own template and the day blocks
    above the header resize week to week.
    """
    for i, row in enumerate(rows):
        labels = {}
        for j, v in enumerate(row):
            if isinstance(v, str) and v.strip().lower() in HEADER_LABELS:
                labels[v.strip().lower()] = j
        if set(HEADER_LABELS) <= labels.keys():
            return Header(row=i, favorite=labels["favorite"],
                          spread=labels["spread"], underdog=labels["underdog"])
    return None


def _looks_like_a_game(row, header: Header) -> bool:
    return (isinstance(_cell(row, header.favorite), str)
            and isinstance(_cell(row, header.underdog), str)
            and isinstance(_cell(row, header.spread), (int, float)))


def count_games(rows, header: Header) -> int:
    """How many rows under this header resolve to a real game. Never raises.

    Used only to choose between tabs that all carry a header. It must not raise, because
    a tab being scored is not necessarily the tab that will be parsed, and a malformed row
    on a tab about to be discarded is not a sheet fault.
    """
    total = 0
    for row in rows[header.row + 1:]:
        if not _looks_like_a_game(row, header):
            continue
        fav_raw, dog_raw = _cell(row, header.favorite), _cell(row, header.underdog)
        try:
            abbr(fav_raw), abbr(dog_raw)
        except ValueError:
            continue
        if float(_cell(row, header.spread)) <= 0:
            continue
        if _is_allcaps(fav_raw) == _is_allcaps(dog_raw):
            continue                      # cannot tell the home team: not a clean game row
        total += 1
    return total


def select_tab(wb):
    """Choose the tab holding this week's board. Returns (name, rows, header).

    THE FIRST TAB IS NOT THE BOARD. The operator's week 2 workbook is
    ['01', 'standing', 'cal', 'Week02']: tab one is last week's finished results, scores
    and everyone's picks already filled in. `wb[wb.sheetnames[0]]` read that tab, and it
    parses -- it is the same game rows with results beside them -- so the engine would
    have priced a week that had already been played and said nothing.

    The last tab is no safer, and neither is a name pattern: he renames these week to week
    and the week 1 file has a single tab called 'Week01'. So the tab is found the same way
    the header row inside it is found, by what actually parses, and an ambiguous workbook
    halts rather than picking.
    """
    examined, candidates = [], []
    for name in wb.sheetnames:
        rows = [[c for c in r] for r in wb[name].iter_rows(values_only=True)]
        header = find_header(rows)
        examined.append(name)
        if header is not None:
            candidates.append((name, rows, header, count_games(rows, header)))

    if not candidates:
        raise SheetFault(
            f"no tab in this workbook carries a Favorite / Spread / Underdog header row. "
            f"Examined {len(examined)}: {', '.join(repr(n) for n in examined)}. The "
            f"operator may have changed his template; do not guess at the tab or the "
            f"columns.")

    best = max(c[3] for c in candidates)
    if best == 0:
        raise SheetFault(
            f"{len(candidates)} tab(s) carry a header row but no game parses beneath any "
            f"of them: {', '.join(repr(c[0]) for c in candidates)}. Examined "
            f"{len(examined)}: {', '.join(repr(n) for n in examined)}.")

    winners = [c for c in candidates if c[3] == best]
    if len(winners) > 1:
        tied = ", ".join(f"{c[0]!r} ({c[3]} games)" for c in winners)
        raise SheetFault(
            f"{len(winners)} tabs parse equally well, so which one is this week's board "
            f"is ambiguous: {tied}. Examined {len(examined)}: "
            f"{', '.join(repr(n) for n in examined)}. Nothing may guess at this -- pass "
            f"the right workbook, or have the stale tab removed.")

    name, rows, header, _ = winners[0]
    return name, rows, header


def parse_sheet(path: str, expected_games: int | None = None,
                neutral_sites: list[tuple[str, str]] | None = None,
                announce=None) -> list[Game]:
    """Read the sheet at `path` and return its games in sheet order.

    `announce`, when given, is called with a one-line description of the tab chosen. The
    caller prints it: which tab was read is the kind of fact that must be on the board,
    because the failure it guards against produced a complete and entirely wrong slate.
    """
    wb = load_workbook(path, data_only=True, read_only=True)
    tab, rows, header = select_tab(wb)
    if announce:
        others = [n for n in wb.sheetnames if n != tab]
        announce(f"tab:   {tab!r}"
                 + (f"  (of {len(wb.sheetnames)}: {', '.join(wb.sheetnames)})"
                    if others else ""))

    header_row, col_fav, col_spread, col_dog = (
        header.row, header.favorite, header.spread, header.underdog)

    neutral = {frozenset(p) for p in (neutral_sites or [])}
    games: list[Game] = []
    current_day = "Unknown"

    for i in range(header_row + 1, len(rows)):
        row = rows[i]
        joined = " ".join(str(v) for v in row if isinstance(v, str))
        day_hit = _DAY_RE.search(joined)

        fav_raw = _cell(row, col_fav)
        dog_raw = _cell(row, col_dog)
        spread_raw = _cell(row, col_spread)

        is_game = (isinstance(fav_raw, str) and isinstance(dog_raw, str)
                   and isinstance(spread_raw, (int, float)))

        if day_hit and not is_game:
            current_day = day_hit.group(1).capitalize()
            continue
        if not is_game:
            continue

        spread = float(spread_raw)
        if spread <= 0:
            raise SheetFault(f"row {i+1}: non-positive spread {spread!r}")
        if float(spread).is_integer():
            # The operator always prints half points so nothing pushes. A whole number
            # means he changed his habit or the cell is wrong. Flag, do not silently accept.
            note = f"spread {spread} is not a half point; the operator always uses half points"
        else:
            note = None

        fav, dog = abbr(fav_raw), abbr(dog_raw)
        if _is_allcaps(fav_raw) and not _is_allcaps(dog_raw):
            nominal_home = fav
        elif _is_allcaps(dog_raw) and not _is_allcaps(fav_raw):
            nominal_home = dog
        else:
            raise SheetFault(
                f"row {i+1}: cannot tell the home team from capitalisation "
                f"({fav_raw!r} vs {dog_raw!r})")

        g = Game(favorite=fav, underdog=dog, spread=spread, day=current_day,
                 nominal_home=nominal_home, row=i + 1)
        if note:
            g.notes.append(note)
        if frozenset((fav, dog)) in neutral:
            g.neutral_site = True
            g.notes.append(
                "declared neutral site: home rules void, the operator's capitalisation "
                "does not mean this team is at home")
        games.append(g)

    if not games:
        raise SheetFault(f"tab {tab!r}: header row found but no games parsed beneath it")
    if expected_games is not None and len(games) != expected_games:
        raise SheetFault(
            f"parsed {len(games)} games, expected {expected_games}. "
            "Halting rather than submitting a partial sheet.")
    return games
