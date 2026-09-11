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


def parse_sheet(path: str, expected_games: int | None = None,
                neutral_sites: list[tuple[str, str]] | None = None) -> list[Game]:
    """Read the sheet at `path` and return its games in sheet order."""
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]

    col_fav = col_spread = col_dog = None
    header_row = None
    for i, row in enumerate(rows):
        labels = {}
        for j, v in enumerate(row):
            if isinstance(v, str):
                key = v.strip().lower()
                if key in ("favorite", "spread", "underdog"):
                    labels[key] = j
        if {"favorite", "spread", "underdog"} <= labels.keys():
            col_fav, col_spread, col_dog = (
                labels["favorite"], labels["spread"], labels["underdog"])
            header_row = i
            break

    if header_row is None:
        raise SheetFault(
            "could not find the Favorite / Spread / Underdog header row. "
            "The operator may have changed his template; do not guess at columns.")

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
        raise SheetFault("header row found but no games parsed beneath it")
    if expected_games is not None and len(games) != expected_games:
        raise SheetFault(
            f"parsed {len(games)} games, expected {expected_games}. "
            "Halting rather than submitting a partial sheet.")
    return games
