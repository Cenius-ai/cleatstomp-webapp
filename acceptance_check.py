#!/usr/bin/env python3
"""CleatStomp acceptance harness.

Exercises the real CLI end to end in isolated temporary directories: the add,
list and suggest happy paths plus the out-of-range float, impossible date, bad
shoe, missing flag value and malformed-file cases. Standard library only.

    python3 acceptance_check.py

Prints one line per case and a pass summary; exits 0 only when every case passes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_NAME = "cleatstomp.py"
STORE = "cleatstomp.json"


class Case:
    """One acceptance case: a name plus the checks it made."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.failures = []

    def check(self, condition: object, description: str) -> None:
        if not condition:
            self.failures.append(description)


def days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def make_workdir() -> Path:
    """A fresh directory holding only a copy of the tool."""

    directory = Path(tempfile.mkdtemp(prefix="cleatstomp-accept-"))
    shutil.copy(HERE / TOOL_NAME, directory / TOOL_NAME)
    return directory


def child_env() -> dict:
    """A plain environment for the child process: UTF-8 output, no colour."""

    env = dict(os.environ)
    env.pop("NO_COLOR", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_tool(workdir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the tool as an argument list — no shell, no string interpolation.

    Each element of ``argv`` is passed straight to execve, so a value such as a
    note containing spaces or quotes can never become part of a command line.
    """

    argv = [sys.executable, str(workdir / TOOL_NAME), *args]
    return subprocess.run(
        argv,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=child_env(),
        shell=False,
        check=False,
    )


def store(workdir: Path) -> Path:
    return workdir / STORE


def read_store(workdir: Path) -> dict:
    return json.loads(store(workdir).read_text(encoding="utf-8"))


def temp_leftovers(workdir: Path) -> list:
    return [path.name for path in workdir.iterdir() if path.name.startswith(".cleatstomp-")]


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #


def case_help(workdir: Path) -> Case:
    case = Case("help lists add, list and suggest and creates no data file")
    result = run_tool(workdir, "--help")
    case.check(result.returncode == 0, "help did not exit 0")
    case.check("add" in result.stdout and "list" in result.stdout and "suggest" in result.stdout,
               "help does not name all three commands")
    case.check("0.0 to 30.0" in result.stdout, "help does not state the 0.0-30.0 range")
    case.check("90 days" in result.stdout, "help does not state the 90-day interval")
    case.check("8.0 degrees" in result.stdout, "help does not state the 8.0-degree drift threshold")
    case.check(not store(workdir).exists(), "help created the data file")
    return case


def case_add_happy_path(workdir: Path) -> Case:
    case = Case("add writes one reading and confirms shoe, date and float")
    result = run_tool(workdir, "add", "--shoe", "Left", "--float", "4.5")
    case.check(result.returncode == 0, "add did not exit 0")
    case.check(result.stderr == "", "add wrote to stderr")
    case.check("Left" in result.stdout, "confirmation omits the shoe")
    case.check(date.today().isoformat() in result.stdout, "confirmation omits today's date")
    case.check("4.5" in result.stdout, "confirmation omits the float angle")
    case.check(store(workdir).exists(), "add did not create the data file")
    if store(workdir).exists():
        payload = read_store(workdir)
        case.check(payload.get("version") == 1, "store has no version field")
        case.check(len(payload.get("entries", [])) == 1, "store does not hold exactly one entry")
    return case


def case_add_second_reading(workdir: Path) -> Case:
    case = Case("a second add keeps the first reading unchanged")
    run_tool(workdir, "add", "--shoe", "Left", "--float", "4.5", "--date", "2024-05-04")
    first = read_store(workdir)["entries"][0]
    result = run_tool(workdir, "add", "--shoe", "Right", "--float", "6.0", "--date", "2024-06-01")
    entries = read_store(workdir)["entries"]
    case.check(result.returncode == 0, "second add did not exit 0")
    case.check(len(entries) == 2, "store does not hold two entries")
    case.check(entries[0] == first, "the first entry changed")
    return case


def case_add_explicit_date_and_note(workdir: Path) -> Case:
    case = Case("add stores and echoes an explicit date and a note")
    note = "right cleat creaks at the top of the stroke"
    result = run_tool(workdir, "add", "--shoe", "left", "--float", "6.25",
                 "--date", "2024-05-04", "--note", note)
    case.check(result.returncode == 0, "add did not exit 0")
    case.check("2024-05-04" in result.stdout, "confirmation omits the date")
    case.check(note in result.stdout, "confirmation omits the note")
    entry = read_store(workdir)["entries"][0]
    case.check(entry["shoe"] == "Left", "lower-case shoe was not stored canonically")
    case.check(entry["date"] == "2024-05-04", "entry date is wrong")
    case.check(entry.get("note") == note, "note was not persisted")
    return case


def case_list(workdir: Path) -> Case:
    case = Case("list groups per shoe with ascending readings and summaries")
    for shoe, angle, day in (
        ("Left", "9.5", "2024-05-04"),
        ("Left", "4.0", "2024-03-02"),
        ("Left", "6.0", "2024-04-11"),
        ("Right", "3.0", "2024-03-20"),
        ("Right", "3.5", "2024-04-25"),
    ):
        run_tool(workdir, "add", "--shoe", shoe, "--float", angle, "--date", day)

    result = run_tool(workdir, "list")
    case.check(result.returncode == 0, "list did not exit 0")
    dates = [line.strip()[:10] for line in result.stdout.splitlines() if line.strip()[:4].isdigit()]
    case.check(dates == ["2024-03-02", "2024-04-11", "2024-05-04", "2024-03-20", "2024-04-25"],
               "readings are not grouped per shoe in ascending date order")
    case.check("count 3" in result.stdout, "missing the Left summary count")
    case.check("count 2" in result.stdout, "missing the Right summary count")
    case.check("latest 9.5" in result.stdout, "missing the Left latest float")
    return case


def case_list_filter(workdir: Path) -> Case:
    case = Case("list --shoe prints one shoe only")
    run_tool(workdir, "add", "--shoe", "Left", "--float", "4.0", "--date", "2024-03-02")
    run_tool(workdir, "add", "--shoe", "Right", "--float", "3.0", "--date", "2024-03-20")
    result = run_tool(workdir, "list", "--shoe", "Left")
    case.check(result.returncode == 0, "list --shoe did not exit 0")
    case.check("Left" in result.stdout, "filtered list omits Left")
    case.check("Right" not in result.stdout, "filtered list still shows Right")
    case.check("count 1" in result.stdout, "filtered list omits the summary")
    return case


def case_list_empty(workdir: Path) -> Case:
    case = Case("list with no readings invites the first one and creates no file")
    result = run_tool(workdir, "list")
    case.check(result.returncode == 0, "empty list did not exit 0")
    case.check("No readings logged yet" in result.stdout, "empty list has no empty-state line")
    case.check("cleatstomp.py add --shoe Left --float 4.5" in result.stdout,
               "empty list has no copy-pasteable add example")
    case.check(not store(workdir).exists(), "empty list created the data file")
    return case


def case_suggest_boundaries() -> Case:
    case = Case("suggest handles 89, 90 and 91 days exactly")
    for days, expect_replace, needle in (
        (91, True, "91 days"),
        (90, True, "90 days"),
        (89, False, "1 day"),
    ):
        workdir = make_workdir()
        try:
            run_tool(workdir, "add", "--shoe", "Left", "--float", "4.0", "--date", days_ago(days))
            result = run_tool(workdir, "suggest")
            line = next((row for row in result.stdout.splitlines() if row.startswith("Left")), "")
            case.check(result.returncode == 0, "suggest did not exit 0 at {} days".format(days))
            case.check(needle in result.stdout, "suggest does not cite {} at {} days".format(needle, days))
            if expect_replace:
                case.check("REPLACE" in line, "suggest did not recommend replacement at {} days".format(days))
            else:
                case.check("REPLACE" not in line, "suggest recommended replacement at {} days".format(days))
                case.check("inside the 90-day interval" in line,
                           "suggest does not report the remaining interval at {} days".format(days))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    return case


def case_suggest_drift() -> Case:
    case = Case("suggest uses the 8.0-degree 30-day float drift")
    high = make_workdir()
    low = make_workdir()
    try:
        run_tool(high, "add", "--shoe", "Left", "--float", "4.0", "--date", days_ago(30))
        run_tool(high, "add", "--shoe", "Left", "--float", "13.0", "--date", days_ago(0))
        high_result = run_tool(high, "suggest")
        line = next((row for row in high_result.stdout.splitlines() if row.startswith("Left")), "")
        case.check("REPLACE" in line, "a 9.0-degree rise did not trigger replacement")
        case.check("9.0" in high_result.stdout, "the measured 9.0-degree rise is not cited")
        case.check("past the 90-day replacement interval" not in high_result.stdout,
                   "the drift verdict wrongly claims the age rule fired")

        run_tool(low, "add", "--shoe", "Left", "--float", "4.0", "--date", days_ago(30))
        run_tool(low, "add", "--shoe", "Left", "--float", "11.0", "--date", days_ago(0))
        low_result = run_tool(low, "suggest")
        line = next((row for row in low_result.stdout.splitlines() if row.startswith("Left")), "")
        case.check("REPLACE" not in line, "a 7.0-degree rise triggered replacement")
        case.check("7.0" in low_result.stdout, "the measured 7.0-degree rise is not cited")
        case.check("below the 8.0" in low_result.stdout, "the below-threshold verdict is missing")
    finally:
        shutil.rmtree(high, ignore_errors=True)
        shutil.rmtree(low, ignore_errors=True)
    return case


def case_suggest_empty(workdir: Path) -> Case:
    case = Case("suggest with no readings invites an add and creates no file")
    result = run_tool(workdir, "suggest")
    case.check(result.returncode == 0, "empty suggest did not exit 0")
    case.check("Not enough data yet" in result.stdout, "empty suggest has no notice")
    case.check("cleatstomp.py add --shoe Left --float 4.0" in result.stdout,
               "empty suggest has no add hint")
    case.check(not store(workdir).exists(), "empty suggest created the data file")
    return case


def case_rejected_inputs(workdir: Path) -> Case:
    case = Case("rejected float, date and shoe leave the store byte-for-byte unchanged")
    run_tool(workdir, "add", "--shoe", "Left", "--float", "4.5", "--date", "2024-05-04")
    before = store(workdir).read_bytes()

    for label, args, needle in (
        ("out-of-range float", ("--shoe", "Left", "--float", "100"), "0.0 and 30.0"),
        ("negative float", ("--shoe", "Left", "--float", "-1"), "0.0 and 30.0"),
        ("non-numeric float", ("--shoe", "Left", "--float", "abc"), "0.0 and 30.0"),
        ("impossible date", ("--shoe", "Left", "--float", "4.0", "--date", "2024-02-30"), "YYYY-MM-DD"),
        ("unknown shoe", ("--shoe", "Middle", "--float", "4.0"), "Left, Right"),
    ):
        result = run_tool(workdir, "add", *args)
        case.check(result.returncode == 1, "{} did not exit 1".format(label))
        case.check(needle in result.stderr, "{} error does not explain the rule".format(label))
        case.check(store(workdir).read_bytes() == before, "{} changed the data file".format(label))
    return case


def case_usage_error(workdir: Path) -> Case:
    case = Case("a missing flag value is an argparse usage error and touches nothing")
    run_tool(workdir, "add", "--shoe", "Left", "--float", "4.5")
    before = store(workdir).read_bytes()
    result = run_tool(workdir, "add", "--shoe", "Left", "--float")
    case.check(result.returncode == 2, "missing flag value did not exit 2")
    case.check("usage:" in result.stderr, "no usage text on the usage error")
    case.check(store(workdir).read_bytes() == before, "usage error changed the data file")
    return case


def case_malformed_store(workdir: Path) -> Case:
    case = Case("a malformed store is reported and never rewritten")
    store(workdir).write_text("{oops", encoding="utf-8")
    before = store(workdir).read_bytes()

    for args in (("add", "--shoe", "Left", "--float", "4.0"), ("list",), ("suggest",)):
        result = run_tool(workdir, *args)
        case.check(result.returncode == 1, "{} on a malformed store did not exit 1".format(args[0]))
        case.check(STORE in result.stderr, "{} error does not name {}".format(args[0], STORE))
        case.check(result.stdout == "", "{} printed to stdout on a malformed store".format(args[0]))
        case.check(store(workdir).read_bytes() == before,
                   "{} modified the malformed file".format(args[0]))
    case.check(temp_leftovers(workdir) == [], "temporary files were left behind")
    return case


def case_many_adds(workdir: Path) -> Case:
    case = Case("fifty back-to-back adds keep the store valid with no temp files")
    for index in range(50):
        shoe = "Left" if index % 2 == 0 else "Right"
        result = run_tool(workdir, "add", "--shoe", shoe, "--float", str(index % 31),
                     "--date", days_ago(index))
        if result.returncode != 0:
            case.check(False, "add {} failed".format(index))
            break
        if len(read_store(workdir)["entries"]) != index + 1:
            case.check(False, "store lost entries after add {}".format(index))
            break
    case.check(temp_leftovers(workdir) == [], "temporary files were left behind")
    return case


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

CASES_WITH_DIR = (
    case_help,
    case_add_happy_path,
    case_add_second_reading,
    case_add_explicit_date_and_note,
    case_list,
    case_list_filter,
    case_list_empty,
    case_suggest_empty,
    case_rejected_inputs,
    case_usage_error,
    case_malformed_store,
    case_many_adds,
)

CASES_NO_DIR = (
    case_suggest_boundaries,
    case_suggest_drift,
)


def main() -> int:
    if not (HERE / TOOL_NAME).exists():
        print("error: {} is missing next to this harness".format(TOOL_NAME), file=sys.stderr)
        return 1

    print("CleatStomp acceptance check — {}".format(HERE / TOOL_NAME))
    results = []

    for check_case in CASES_WITH_DIR:
        workdir = make_workdir()
        try:
            results.append(check_case(workdir))
        except (OSError, ValueError, KeyError) as error:  # harness bug or crashed case
            broken = Case(check_case.__name__)
            broken.check(False, "case crashed: {!r}".format(error))
            results.append(broken)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    for check_case in CASES_NO_DIR:
        try:
            results.append(check_case())
        except (OSError, ValueError, KeyError) as error:
            broken = Case(check_case.__name__)
            broken.check(False, "case crashed: {!r}".format(error))
            results.append(broken)

    failures = 0
    for result in results:
        if result.failures:
            failures += 1
            print("FAIL  {}".format(result.name))
            for failure in result.failures:
                print("        - {}".format(failure))
        else:
            print("PASS  {}".format(result.name))

    total = len(results)
    print()
    if failures:
        print("{} of {} cases failed".format(failures, total))
        return 1
    print("All {} acceptance cases passed".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
