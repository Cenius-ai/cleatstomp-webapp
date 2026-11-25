#!/usr/bin/env python3
"""CleatStomp — log bicycle pedal cleat float wear and get replacement advice.

One file, standard library only. Readings live in ``./cleatstomp.json`` in the
directory the tool is run from. Every write goes through a temporary file and
``os.replace`` so an interrupted write can never truncate existing history.

Commands: ``add`` (log a reading), ``list`` (per-shoe history) and ``suggest``
(replacement advice from a fixed 90-day interval and an 8.0-degree float-drift
signal over the trailing 30 days).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta

__version__ = "1.0.0"

PROGRAM = "cleatstomp.py"
DATA_FILE = "cleatstomp.json"
STORE_VERSION = 1

SHOES = ("Left", "Right")
MIN_FLOAT = 0.0
MAX_FLOAT = 30.0

REPLACEMENT_DAYS = 90
DRIFT_WINDOW_DAYS = 30
DRIFT_THRESHOLD = 8.0

EXIT_OK = 0
EXIT_ERROR = 1

STORE_HINT = (
    "Fix or move cleatstomp.json aside, then re-run. "
    "The file was left exactly as it was."
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class CliError(Exception):
    """A user-facing problem: the message goes to stderr and the tool exits 1."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class DataFileError(CliError):
    """``./cleatstomp.json`` is malformed, unreadable or unwritable."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__("cannot use {}: {}".format(path, reason), STORE_HINT)
        self.path = path


# --------------------------------------------------------------------------- #
# Styling — the committed terminal palette (accent #b36136, see DESIGN.md)
# --------------------------------------------------------------------------- #


class Style:
    """ANSI styling that switches itself off for pipes, files and NO_COLOR."""

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    ACCENT = "\x1b[38;2;179;97;54m"  # oklch(0.58 0.12 47) -> #b36136
    MUTED = "\x1b[38;2;150;145;137m"  # neutral ramp, secondary text
    STRONG = "\x1b[38;2;233;229;222m"  # neutral ramp, primary text

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, text: str, prefix: str) -> str:
        if not self.enabled or not text:
            return text
        return "{}{}{}".format(prefix, text, self.RESET)

    def accent(self, text: str) -> str:
        return self._wrap(text, self.ACCENT)

    def muted(self, text: str) -> str:
        return self._wrap(text, self.MUTED)

    def strong(self, text: str) -> str:
        return self._wrap(text, self.ACCENT + self.BOLD)


def make_style(disabled: bool) -> Style:
    """Colour only when the stream is a terminal, NO_COLOR is unset and not asked."""

    enabled = (
        not disabled
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )
    return Style(enabled)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def canonical_shoe(raw: str) -> str:
    """Return 'Left' or 'Right' for any casing of those words."""

    wanted = str(raw).strip().lower()
    for shoe in SHOES:
        if shoe.lower() == wanted:
            return shoe
    raise CliError(
        "--shoe must be {} (got {!r}); accepted values: {}".format(
            " or ".join(SHOES), raw, ", ".join(SHOES)
        )
    )


def parse_float_angle(raw: str) -> float:
    """Parse a float angle, rejecting non-numbers and anything outside 0.0-30.0."""

    try:
        value = float(str(raw).strip())
    except ValueError:
        raise CliError(
            "--float must be a number between {:.1f} and {:.1f} degrees (got {!r})".format(
                MIN_FLOAT, MAX_FLOAT, raw
            )
        ) from None
    # NaN and infinities fail this comparison, as do out-of-range numbers.
    if not (MIN_FLOAT <= value <= MAX_FLOAT):
        raise CliError(
            "--float must be between {:.1f} and {:.1f} degrees (got {!r})".format(
                MIN_FLOAT, MAX_FLOAT, raw
            )
        )
    return value


def looks_like_iso_date(text: str) -> bool:
    """True for exactly ``YYYY-MM-DD`` with ASCII digits (calendar unknown)."""

    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return False
    digits = text[:4] + text[5:7] + text[8:]
    return all(character in "0123456789" for character in digits)


def parse_iso_date(raw: str, flag: str = "--date") -> str:
    """Validate a real calendar date and return it unchanged in ISO form."""

    text = str(raw).strip()
    failure = CliError(
        "{} must be a real calendar date in YYYY-MM-DD format (got {!r})".format(flag, raw)
    )
    if not looks_like_iso_date(text):
        raise failure
    try:
        date.fromisoformat(text)
    except ValueError:
        raise failure from None
    return text


def normalise_note(raw: str | None) -> str | None:
    """Trim a note; an empty note is stored as absent."""

    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


class Entry:
    """One logged cleat float reading; assign the fields once, then treat as read-only."""

    __slots__ = ("shoe", "date", "float_angle", "note")

    def __init__(
        self,
        shoe: str,
        date: str,
        float_angle: float,
        note: str | None = None,
    ) -> None:
        self.shoe = shoe
        self.date = date
        self.float_angle = float_angle
        self.note = note

    def to_json(self) -> dict:
        payload = {
            "shoe": self.shoe,
            "date": self.date,
            "float_angle": self.float_angle,
        }
        if self.note:
            payload["note"] = self.note
        return payload

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entry):
            return NotImplemented
        return (
            self.shoe == other.shoe
            and self.date == other.date
            and self.float_angle == other.float_angle
            and self.note == other.note
        )

    def __hash__(self) -> int:
        return hash((self.shoe, self.date, self.float_angle, self.note))

    def __repr__(self) -> str:
        return "Entry(shoe={!r}, date={!r}, float_angle={!r}, note={!r})".format(
            self.shoe, self.date, self.float_angle, self.note
        )


class ShoeSummary:
    """Derived read-only view of one shoe's readings; never persisted."""

    __slots__ = (
        "shoe",
        "readings",
        "count",
        "first_date",
        "last_date",
        "latest_float",
        "drift_30d",
        "days_since_first",
        "days_remaining",
        "due_to_age",
        "due_to_drift",
    )

    def __init__(
        self,
        shoe: str,
        readings: list,
        count: int,
        first_date: str,
        last_date: str,
        latest_float: float,
        drift_30d: float | None,
        days_since_first: int,
        days_remaining: int,
        due_to_age: bool,
        due_to_drift: bool,
    ) -> None:
        self.shoe = shoe
        self.readings = readings
        self.count = count
        self.first_date = first_date
        self.last_date = last_date
        self.latest_float = latest_float
        self.drift_30d = drift_30d
        self.days_since_first = days_since_first
        self.days_remaining = days_remaining
        self.due_to_age = due_to_age
        self.due_to_drift = due_to_drift

    @property
    def replacement_due(self) -> bool:
        return self.due_to_age or self.due_to_drift


# --------------------------------------------------------------------------- #
# Store: read, validate, write atomically
# --------------------------------------------------------------------------- #


def store_path() -> str:
    """``./cleatstomp.json`` in the current working directory."""

    return os.path.join(os.getcwd(), DATA_FILE)


def load_entries(path: str) -> list:
    """Read every entry; a missing file is an empty log, a broken one is an error."""

    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_text = handle.read()
    except OSError as exc:
        raise DataFileError(path, "could not read it ({})".format(exc.strerror or exc)) from None
    except UnicodeDecodeError as exc:
        raise DataFileError(path, "could not read it as UTF-8 text ({})".format(exc.reason)) from None

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DataFileError(
            path,
            "not valid JSON ({} at line {} column {})".format(exc.msg, exc.lineno, exc.colno),
        ) from None
    return entries_from_payload(payload, path)


def entries_from_payload(payload: object, path: str) -> list:
    if not isinstance(payload, dict):
        raise DataFileError(path, "expected a JSON object with 'version' and 'entries'")

    version = payload.get("version", STORE_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise DataFileError(path, "the 'version' field must be a positive integer")
    if version > STORE_VERSION:
        raise DataFileError(
            path,
            "it was written by a newer CleatStomp (store version {}; this build reads {})".format(
                version, STORE_VERSION
            ),
        )

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise DataFileError(path, "expected an 'entries' list")
    return [entry_from_json(item, index, path) for index, item in enumerate(raw_entries)]


def entry_from_json(item: object, index: int, path: str) -> Entry:
    where = "entry {}".format(index + 1)
    if not isinstance(item, dict):
        raise DataFileError(path, "{} is not a JSON object".format(where))

    shoe = item.get("shoe")
    if shoe not in SHOES:
        raise DataFileError(
            path,
            "{} has shoe {!r}; expected one of {}".format(where, shoe, ", ".join(SHOES)),
        )

    raw_date = item.get("date")
    if not isinstance(raw_date, str) or not looks_like_iso_date(raw_date):
        raise DataFileError(path, "{} has date {!r}; expected YYYY-MM-DD".format(where, raw_date))
    try:
        date.fromisoformat(raw_date)
    except ValueError:
        raise DataFileError(
            path,
            "{} has date {!r}, which is not a real calendar date".format(where, raw_date),
        ) from None

    angle = item.get("float_angle")
    if isinstance(angle, bool) or not isinstance(angle, (int, float)):
        raise DataFileError(path, "{} has float_angle {!r}; expected a number".format(where, angle))
    if not (MIN_FLOAT <= angle <= MAX_FLOAT):
        raise DataFileError(
            path,
            "{} has float_angle {!r}; expected a number between {:.1f} and {:.1f}".format(
                where, angle, MIN_FLOAT, MAX_FLOAT
            ),
        )

    note = item.get("note")
    if note is not None and not isinstance(note, str):
        raise DataFileError(path, "{} has a note that is not text".format(where))
    return Entry(shoe=shoe, date=raw_date, float_angle=float(angle), note=note or None)


def save_entries(path: str, entries: list) -> None:
    """Write the whole log through a temporary file plus an atomic replace."""

    payload = {
        "version": STORE_VERSION,
        "entries": [entry.to_json() for entry in entries],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    directory = os.path.dirname(os.path.abspath(path)) or "."
    temp_path = ""
    try:
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".cleatstomp-", suffix=".tmp", dir=directory
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = ""
    except OSError as exc:
        raise DataFileError(path, "could not write it ({})".format(exc.strerror or exc)) from None
    finally:
        if temp_path:
            remove_quietly(temp_path)


def remove_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        print(
            "cleatstomp: warning: could not remove temporary file {} ({})".format(
                path, exc.strerror or exc
            ),
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- #
# Summaries and advice
# --------------------------------------------------------------------------- #


def summarise_shoes(shoes: list, entries: list, today: date) -> list:
    """Summaries for the requested shoes, skipping those with no readings."""

    summaries = (summarise(shoe, entries, today) for shoe in shoes)
    return [summary for summary in summaries if summary is not None]


def summarise(shoe: str, entries: list, today: date) -> ShoeSummary | None:
    """Derive one shoe's history summary; None when the shoe has no readings."""

    readings = sorted(
        (entry for entry in entries if entry.shoe == shoe), key=lambda entry: entry.date
    )
    if not readings:
        return None

    first_day = date.fromisoformat(readings[0].date)
    days_since_first = (today - first_day).days
    drift = drift_over_window(readings, today)

    return ShoeSummary(
        shoe=shoe,
        readings=readings,
        count=len(readings),
        first_date=readings[0].date,
        last_date=readings[-1].date,
        latest_float=readings[-1].float_angle,
        drift_30d=drift,
        days_since_first=days_since_first,
        days_remaining=REPLACEMENT_DAYS - days_since_first,
        due_to_age=days_since_first >= REPLACEMENT_DAYS,
        due_to_drift=drift is not None and drift >= DRIFT_THRESHOLD,
    )


def drift_over_window(readings: list, today: date) -> float | None:
    """Float rise from the earliest to the latest reading in the trailing 30 days."""

    window_start = today - timedelta(days=DRIFT_WINDOW_DAYS)
    in_window = [
        entry
        for entry in readings
        if window_start <= date.fromisoformat(entry.date) <= today
    ]
    if len(in_window) < 2:
        return None
    return round(in_window[-1].float_angle - in_window[0].float_angle, 6)


def format_angle(value: float) -> str:
    """Render an angle with at least one decimal: 4.0, 4.5, 4.55."""

    text = "{:.2f}".format(value).rstrip("0")
    if text.endswith("."):
        text += "0"
    return text + "\u00b0"


def plural(count: int, noun: str) -> str:
    return "{} {}{}".format(count, noun, "" if count == 1 else "s")


def drift_text(drift: float | None) -> str:
    """One phrase describing the 30-day float drift and how it compares to the threshold."""

    if drift is None:
        return "float rise not yet measurable (needs two readings inside the last {} days)".format(
            DRIFT_WINDOW_DAYS
        )
    if drift < 0:
        return "float fell {} over the last {} days (below the {:.1f}\u00b0 threshold)".format(
            format_angle(abs(drift)), DRIFT_WINDOW_DAYS, DRIFT_THRESHOLD
        )
    if drift >= DRIFT_THRESHOLD:
        return "float rise {} over the last {} days (at or above the {:.1f}\u00b0 threshold)".format(
            format_angle(drift), DRIFT_WINDOW_DAYS, DRIFT_THRESHOLD
        )
    return "float rise {} over the last {} days (below the {:.1f}\u00b0 threshold)".format(
        format_angle(drift), DRIFT_WINDOW_DAYS, DRIFT_THRESHOLD
    )


# --------------------------------------------------------------------------- #
# add
# --------------------------------------------------------------------------- #


def cmd_add(args: argparse.Namespace, style: Style) -> int:
    shoe = canonical_shoe(args.shoe)
    angle = parse_float_angle(args.float_angle)
    reading_date = date.today().isoformat() if args.date is None else parse_iso_date(args.date)
    note = normalise_note(args.note)

    path = store_path()
    entries = load_entries(path)
    entries.append(Entry(shoe=shoe, date=reading_date, float_angle=angle, note=note))
    save_entries(path, entries)

    confirmation = "Saved {} reading for {}: float {}{}".format(
        style.strong(shoe),
        reading_date,
        format_angle(angle),
        "" if note is None else " \u2014 note: {}".format(note),
    )
    print(confirmation)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def cmd_list(args: argparse.Namespace, style: Style) -> int:
    wanted = list(SHOES) if args.shoe is None else [canonical_shoe(args.shoe)]
    path = store_path()
    entries = load_entries(path)

    summaries = summarise_shoes(wanted, entries, date.today())
    if not summaries:
        hint_shoe = "Left" if args.shoe is None else wanted[0]
        print(style.strong(empty_heading(args.shoe, hint_shoe)))
        print()
        print("Log the first one:")
        print("  python3 {} add --shoe {} --float 4.5".format(PROGRAM, hint_shoe))
        return EXIT_OK

    angle_width = max(
        [len("float")]
        + [
            len(format_angle(reading.float_angle))
            for summary in summaries
            for reading in summary.readings
        ]
    )
    blocks = [render_shoe_section(summary, angle_width, style) for summary in summaries]
    print("\n\n".join(blocks))
    return EXIT_OK


def empty_heading(shoe_filter: str | None, shoe: str) -> str:
    """Empty-state wording that stays honest when a shoe filter is active."""

    if shoe_filter is not None:
        return "No readings logged yet for {}.".format(shoe)
    return "No readings logged yet."


def render_shoe_section(summary: ShoeSummary, angle_width: int, style: Style) -> str:
    has_notes = any(reading.note for reading in summary.readings)
    heading = "{} \u2014 {}".format(summary.shoe, plural(summary.count, "reading"))
    header = "  {}  {}".format("date".ljust(10), "float".ljust(angle_width))
    lines = [style.strong(heading), style.muted(header + ("  note" if has_notes else ""))]

    for reading in summary.readings:
        row = "  {}  {}".format(
            reading.date.ljust(10), format_angle(reading.float_angle).ljust(angle_width)
        )
        if has_notes:
            row += "  " + (reading.note or "")
        lines.append(row.rstrip())

    lines.append(style.muted("  " + "\u2500" * 52))
    lines.append("  " + summary_line(summary))
    return "\n".join(lines)


def summary_line(summary: ShoeSummary) -> str:
    return "count {} \u00b7 first {} \u00b7 last {} \u00b7 latest {}".format(
        summary.count,
        summary.first_date,
        summary.last_date,
        format_angle(summary.latest_float),
    )


# --------------------------------------------------------------------------- #
# suggest
# --------------------------------------------------------------------------- #


def cmd_suggest(args: argparse.Namespace, style: Style) -> int:
    today = date.today()
    wanted = list(SHOES) if args.shoe is None else [canonical_shoe(args.shoe)]
    path = store_path()
    entries = load_entries(path)

    summaries = summarise_shoes(wanted, entries, today)
    if not summaries:
        print(style.strong("Not enough data yet."))
        print()
        if args.shoe is None:
            print("No readings logged yet, so there is nothing to advise on.")
        else:
            print(
                "No readings logged yet for {}, so there is nothing to advise on.".format(
                    wanted[0]
                )
            )
        print("Log a reading and run suggest again:")
        print("  python3 {} add --shoe {} --float 4.0".format(PROGRAM, wanted[0]))
        return EXIT_OK

    blocks = [render_advice(summary, style) for summary in summaries]
    print("\n".join(blocks))
    return EXIT_OK


def render_advice(summary: ShoeSummary, style: Style) -> str:
    verdict, reason = advice_verdict(summary)
    padded_verdict = style.strong(verdict.ljust(7))
    lines = ["{:<6} {} {}".format(summary.shoe, padded_verdict, reason)]
    lines.append(
        "       {} \u00b7 latest {} on {} \u00b7 {}".format(
            style.muted("first reading {} ({})".format(summary.first_date, age_label(summary))),
            format_angle(summary.latest_float),
            summary.last_date,
            drift_text(summary.drift_30d),
        )
    )
    return "\n".join(lines)


def age_label(summary: ShoeSummary) -> str:
    """Human phrasing for how long ago the shoe's first reading was logged."""

    days = summary.days_since_first
    if days == 0:
        return "logged today"
    if days == 1:
        return "1 day ago"
    if days < 0:
        return "dated {} in the future".format(plural(abs(days), "day"))
    return "{} ago".format(plural(days, "day"))


def advice_verdict(summary: ShoeSummary) -> tuple[str, str]:
    """Return the (verdict, reason) pair for one shoe."""

    age_text = age_clause(summary)
    if summary.due_to_age and summary.due_to_drift:
        return "REPLACE", "{} and {}".format(age_text, drift_clause(summary))
    if summary.due_to_age:
        return "REPLACE", "{} \u2014 past the {}-day replacement interval".format(
            age_text, REPLACEMENT_DAYS
        )
    if summary.due_to_drift:
        return "REPLACE", "{} \u2014 at or past the {:.1f}\u00b0 float-drift threshold".format(
            drift_clause(summary), DRIFT_THRESHOLD
        )
    return "OK", "inside the {}-day interval \u2014 {} remaining".format(
        REPLACEMENT_DAYS, plural(summary.days_remaining, "day")
    )


def age_clause(summary: ShoeSummary) -> str:
    """The age half of a replacement verdict; only reachable at 90+ days."""

    return "cleat is {} old (first reading {})".format(
        plural(summary.days_since_first, "day"), summary.first_date
    )


def drift_clause(summary: ShoeSummary) -> str:
    rise = summary.drift_30d if summary.drift_30d is not None else 0.0
    return "float rose {} over the last {} days".format(
        format_angle(rise), DRIFT_WINDOW_DAYS
    )


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--no-color",
        action="store_true",
        help="never emit ANSI colour (also honoured: the NO_COLOR environment variable)",
    )

    epilog = (
        "rules\n"
        "  float angle           {min:.1f} to {max:.1f} degrees inclusive\n"
        "  replacement interval  {interval} days from a shoe's earliest reading\n"
        "  float-drift signal    a rise of {threshold:.1f} degrees or more\n"
        "                        between the earliest and latest reading inside\n"
        "                        the trailing {window} days\n"
        "\n"
        "examples\n"
        "  python3 {prog} add --shoe Left --float 4.5\n"
        "  python3 {prog} add --shoe right --float 6.25 --date 2024-05-04 \\\n"
        "      --note 'right cleat creaks at the top of the stroke'\n"
        "  python3 {prog} list\n"
        "  python3 {prog} list --shoe Left\n"
        "  python3 {prog} suggest\n"
        "  python3 {prog} suggest --shoe Right\n"
        "\n"
        "readings are stored in ./{data} in the directory you run the tool from\n"
    ).format(
        min=MIN_FLOAT,
        max=MAX_FLOAT,
        interval=REPLACEMENT_DAYS,
        threshold=DRIFT_THRESHOLD,
        window=DRIFT_WINDOW_DAYS,
        prog=PROGRAM,
        data=DATA_FILE,
    )

    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "CleatStomp {version} \u2014 log bicycle pedal cleat float wear and get\n"
            "replacement advice. Every reading is one float angle for one shoe."
        ).format(version=__version__),
        epilog=epilog,
    )
    parser.add_argument(
        "--version", action="version", version="{} {}".format(PROGRAM, __version__)
    )

    commands = parser.add_subparsers(dest="command", metavar="command")

    add_parser = commands.add_parser(
        "add",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="log one cleat float reading for one shoe",
        description="Log one cleat float reading for one shoe.",
        epilog=(
            "examples\n"
            "  python3 {prog} add --shoe Left --float 4.5\n"
            "  python3 {prog} add --shoe right --float 6.25 --date 2024-05-04 \\\n"
            "      --note 'right cleat creaks at the top of the stroke'\n"
            "\n"
            "left/right are accepted in any casing and stored as Left/Right.\n"
            "--float must be within {min:.1f} to {max:.1f} degrees inclusive.\n"
            "--date defaults to today and must be a real YYYY-MM-DD calendar date.\n"
            "A rejected reading never creates or changes {data}.\n"
        ).format(prog=PROGRAM, min=MIN_FLOAT, max=MAX_FLOAT, data=DATA_FILE),
    )
    add_parser.add_argument("--shoe", required=True, help="Left or Right (any casing)")
    add_parser.add_argument(
        "--float",
        dest="float_angle",
        required=True,
        help="float angle in degrees, {:.1f} to {:.1f} inclusive".format(MIN_FLOAT, MAX_FLOAT),
    )
    add_parser.add_argument("--date", help="reading date as YYYY-MM-DD (default: today)")
    add_parser.add_argument("--note", help="optional free-text note stored with the reading")

    list_parser = commands.add_parser(
        "list",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="show logged wear history per shoe",
        description="Show logged wear history per shoe in ascending date order.",
        epilog=(
            "examples\n"
            "  python3 {prog} list\n"
            "  python3 {prog} list --shoe Left\n"
            "\n"
            "each section is followed by a summary line: count, first date,\n"
            "last date and latest float angle.\n"
            "This command never creates or changes {data}.\n"
        ).format(prog=PROGRAM, data=DATA_FILE),
    )
    list_parser.add_argument("--shoe", help="only show this shoe (Left or Right)")

    suggest_parser = commands.add_parser(
        "suggest",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="advise on cleat replacement from age and float drift",
        description="Advise on cleat replacement per shoe.",
        epilog=(
            "examples\n"
            "  python3 {prog} suggest\n"
            "  python3 {prog} suggest --shoe Right\n"
            "\n"
            "replacement is suggested when a shoe is {interval} days or older\n"
            "(counted from its earliest reading) or when its float rose by\n"
            "{threshold:.1f} degrees or more inside the trailing {window} days.\n"
            "This command never creates or changes {data}.\n"
        ).format(
            prog=PROGRAM,
            interval=REPLACEMENT_DAYS,
            threshold=DRIFT_THRESHOLD,
            window=DRIFT_WINDOW_DAYS,
            data=DATA_FILE,
        ),
    )
    suggest_parser.add_argument("--shoe", help="only advise on this shoe (Left or Right)")

    return parser


def no_command_hint(style: Style) -> None:
    print()
    print(style.strong("Start here:"))
    print("  python3 {} add --shoe Left --float 4.5".format(PROGRAM))
    print("  python3 {} list".format(PROGRAM))
    print("  python3 {} suggest".format(PROGRAM))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run(argv: list, style: Style) -> int:
    parser = build_parser()
    if not argv:
        parser.print_help()
        no_command_hint(style)
        return EXIT_OK

    args = parser.parse_args(argv)
    if args.command == "add":
        return cmd_add(args, style)
    if args.command == "list":
        return cmd_list(args, style)
    if args.command == "suggest":
        return cmd_suggest(args, style)

    parser.print_help()
    no_command_hint(style)
    return EXIT_OK


def ensure_utf8_streams() -> None:
    """Print UTF-8 even on a legacy terminal locale, so degrees and rules render."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            continue


def silence_broken_pipe() -> None:
    """Point stdout at /dev/null after a closed pipe so shutdown stays quiet."""

    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except OSError:
        return


def main(argv: list | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    ensure_utf8_streams()
    style = make_style(disabled="--no-color" in arguments)

    try:
        exit_code = run(arguments, style)
        sys.stdout.flush()
        return exit_code
    except CliError as error:
        print("cleatstomp: error: {}".format(error.message), file=sys.stderr)
        if error.hint:
            print("cleatstomp: hint: {}".format(error.hint), file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:
        silence_broken_pipe()
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("cleatstomp: interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
