"""End-to-end and unit tests for the CleatStomp CLI.

Every CLI test runs the real tool as a subprocess in an isolated temporary
directory, so the assertions cover exactly what a user gets: stdout, stderr,
exit code and the bytes of ./cleatstomp.json.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "cleatstomp.py"
STORE = "cleatstomp.json"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def run_tool(workdir, *args, extra_env=None):
    """Run cleatstomp.py in ``workdir`` and capture the full process result."""

    env = dict(os.environ)
    env.pop("NO_COLOR", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    argv = [sys.executable, str(workdir / "cleatstomp.py"), *args]
    return subprocess.run(
        argv,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=env,
        shell=False,
        check=False,
    )


def days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


def store_file(workdir):
    return Path(workdir) / STORE


def read_store(workdir):
    return json.loads(store_file(workdir).read_text(encoding="utf-8"))


def add(workdir, *args):
    return run_tool(workdir, "add", *args)


@pytest.fixture
def workdir(tmp_path):
    """A clean directory holding only the tool."""

    target = tmp_path / "cleat-work"
    target.mkdir()
    shutil.copy(TOOL, target / "cleatstomp.py")
    return target


# --------------------------------------------------------------------------- #
# Help, version and bare invocation
# --------------------------------------------------------------------------- #


def test_help_lists_all_commands_and_creates_no_store(workdir):
    result = run_tool(workdir, "--help")

    assert result.returncode == 0
    assert result.stderr == ""
    for command in ("add", "list", "suggest"):
        assert command in result.stdout
    assert "0.0 to 30.0" in result.stdout
    assert "90 days" in result.stdout
    assert "8.0 degrees" in result.stdout
    assert store_file(workdir).exists() is False


def test_subcommand_help_shows_flags_and_an_example(workdir):
    for command, flags in (
        ("add", ("--shoe", "--float", "--date", "--note")),
        ("list", ("--shoe",)),
        ("suggest", ("--shoe",)),
    ):
        result = run_tool(workdir, command, "--help")
        assert result.returncode == 0
        for flag in flags:
            assert flag in result.stdout
        assert "python3 cleatstomp.py {}".format(command) in result.stdout
    assert store_file(workdir).exists() is False


def test_version_flag(workdir):
    result = run_tool(workdir, "--version")

    assert result.returncode == 0
    assert "cleatstomp.py 1.0.0" in result.stdout


def test_bare_invocation_prints_usage_and_exits_zero(workdir):
    result = run_tool(workdir)

    assert result.returncode == 0
    assert "add" in result.stdout and "suggest" in result.stdout
    assert "python3 cleatstomp.py add --shoe Left --float 4.5" in result.stdout
    assert store_file(workdir).exists() is False


def test_output_is_plain_when_not_a_tty(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.5")
    result = run_tool(workdir, "list")

    assert "\x1b[" not in result.stdout
    assert result.returncode == 0


# --------------------------------------------------------------------------- #
# add
# --------------------------------------------------------------------------- #


def test_add_creates_store_and_confirms_every_field(workdir):
    result = add(workdir, "--shoe", "Left", "--float", "4.5")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Left" in result.stdout
    assert date.today().isoformat() in result.stdout
    assert "4.5" in result.stdout

    payload = read_store(workdir)
    assert payload["version"] == 1
    assert payload["entries"] == [
        {"shoe": "Left", "date": date.today().isoformat(), "float_angle": 4.5}
    ]


def test_add_second_reading_keeps_the_first_unchanged(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.5", "--date", "2024-05-04")
    first_snapshot = read_store(workdir)["entries"][0]

    result = add(workdir, "--shoe", "Right", "--float", "6.0", "--date", "2024-06-01")

    assert result.returncode == 0
    entries = read_store(workdir)["entries"]
    assert len(entries) == 2
    assert entries[0] == first_snapshot
    assert entries[1] == {"shoe": "Right", "date": "2024-06-01", "float_angle": 6.0}


def test_add_accepts_explicit_date_and_echoes_it(workdir):
    result = add(workdir, "--shoe", "Left", "--float", "4.5", "--date", "2024-05-04")

    assert result.returncode == 0
    assert "2024-05-04" in result.stdout
    assert read_store(workdir)["entries"][0]["date"] == "2024-05-04"


def test_add_normalises_shoe_casing(workdir):
    add(workdir, "--shoe", "left", "--float", "4.5")
    add(workdir, "--shoe", "RIGHT", "--float", "5.0")

    shoes = [entry["shoe"] for entry in read_store(workdir)["entries"]]
    assert shoes == ["Left", "Right"]


def test_add_stores_and_echoes_a_note(workdir):
    note = "right cleat creaks at the top of the stroke"
    result = add(workdir, "--shoe", "Left", "--float", "4.5", "--note", note)

    assert result.returncode == 0
    assert note in result.stdout
    assert read_store(workdir)["entries"][0]["note"] == note


def test_add_without_note_omits_the_field(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.5")

    assert "note" not in read_store(workdir)["entries"][0]


def test_add_accepts_boundary_float_values(workdir):
    assert add(workdir, "--shoe", "Left", "--float", "0").returncode == 0
    assert add(workdir, "--shoe", "Left", "--float", "30").returncode == 0

    angles = [entry["float_angle"] for entry in read_store(workdir)["entries"]]
    assert angles == [0.0, 30.0]


# --------------------------------------------------------------------------- #
# add — rejected input never touches the store
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded(workdir):
    """A directory whose store already holds one reading."""

    assert add(workdir, "--shoe", "Left", "--float", "4.5", "--date", "2024-05-04").returncode == 0
    return workdir


@pytest.mark.parametrize("bad_date", ["2024-02-30", "2024-13-01", "2024-00-10", "2024-5-4", "04/05/2024", "yesterday", ""])
def test_add_rejects_impossible_dates_without_touching_the_store(seeded, bad_date):
    before = store_file(seeded).read_bytes()

    result = add(seeded, "--shoe", "Left", "--float", "4.0", "--date", bad_date)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "YYYY-MM-DD" in result.stderr
    assert store_file(seeded).read_bytes() == before


@pytest.mark.parametrize("bad_float", ["abc", "-1", "-0.1", "30.01", "100", "nan", "inf", "4,5"])
def test_add_rejects_bad_floats_without_touching_the_store(seeded, bad_float):
    before = store_file(seeded).read_bytes()

    result = add(seeded, "--shoe", "Left", "--float", bad_float)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "0.0 and 30.0" in result.stderr
    assert store_file(seeded).read_bytes() == before


@pytest.mark.parametrize("bad_shoe", ["Middle", "both", "", "lef"])
def test_add_rejects_unknown_shoes_and_lists_allowed_values(seeded, bad_shoe):
    before = store_file(seeded).read_bytes()

    result = add(seeded, "--shoe", bad_shoe, "--float", "4.0")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Left" in result.stderr and "Right" in result.stderr
    assert store_file(seeded).read_bytes() == before


def test_rejected_input_never_creates_the_store(workdir):
    for args in (
        ("--shoe", "Middle", "--float", "4.0"),
        ("--shoe", "Left", "--float", "99"),
        ("--shoe", "Left", "--float", "4.0", "--date", "2024-02-30"),
    ):
        assert add(workdir, *args).returncode == 1
        assert store_file(workdir).exists() is False


def test_missing_float_value_is_an_argparse_usage_error(seeded):
    before = store_file(seeded).read_bytes()

    result = add(seeded, "--shoe", "Left", "--float")

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert store_file(seeded).read_bytes() == before


def test_missing_required_shoe_is_an_argparse_usage_error(seeded):
    before = store_file(seeded).read_bytes()

    result = add(seeded, "--float", "4.0")

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert store_file(seeded).read_bytes() == before


# --------------------------------------------------------------------------- #
# Broken store file
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "contents",
    [
        "{oops",
        "",
        "[]",
        '{"version": 1}',
        '{"version": 1, "entries": "nope"}',
        '{"version": 1, "entries": [{"shoe": "Middle", "date": "2024-05-04", "float_angle": 4.0}]}',
        '{"version": 1, "entries": [{"shoe": "Left", "date": "2024-02-30", "float_angle": 4.0}]}',
        '{"version": 1, "entries": [{"shoe": "Left", "date": "2024-05-04", "float_angle": 88.0}]}',
    ],
)
def test_every_command_reports_a_broken_store_and_leaves_it_alone(workdir, contents):
    store_file(workdir).write_text(contents, encoding="utf-8")
    before = store_file(workdir).read_bytes()

    for args in (
        ("add", "--shoe", "Left", "--float", "4.0"),
        ("list",),
        ("suggest",),
    ):
        result = run_tool(workdir, *args)
        assert result.returncode == 1, args
        assert STORE in result.stderr, args
        assert result.stdout == "", args
        assert store_file(workdir).read_bytes() == before, args

    leftovers = [path.name for path in Path(workdir).iterdir() if path.name.startswith(".cleatstomp-")]
    assert leftovers == []


def test_broken_store_error_names_the_path_and_stays_quiet_on_stdout(workdir):
    store_file(workdir).write_text("{oops", encoding="utf-8")

    result = run_tool(workdir, "list")

    assert result.returncode == 1
    assert str(store_file(workdir)) in result.stderr
    assert "not valid JSON" in result.stderr
    assert result.stdout == ""


def test_newer_store_version_is_refused(workdir):
    store_file(workdir).write_text('{"version": 9, "entries": []}', encoding="utf-8")

    result = run_tool(workdir, "list")

    assert result.returncode == 1
    assert "newer CleatStomp" in result.stderr


def test_fifty_back_to_back_adds_keep_the_store_valid(workdir):
    for index in range(50):
        shoe = "Left" if index % 2 == 0 else "Right"
        result = add(
            workdir,
            "--shoe",
            shoe,
            "--float",
            str(index % 31),
            "--date",
            days_ago(index),
        )
        assert result.returncode == 0
        payload = json.loads(store_file(workdir).read_text(encoding="utf-8"))
        assert len(payload["entries"]) == index + 1

    leftovers = [path.name for path in Path(workdir).iterdir() if path.name.startswith(".cleatstomp-")]
    assert leftovers == []
    assert len(read_store(workdir)["entries"]) == 50


def test_read_only_commands_never_change_the_store(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.5")
    add(workdir, "--shoe", "Right", "--float", "5.5")
    before = store_file(workdir).read_bytes()

    assert run_tool(workdir, "list").returncode == 0
    assert run_tool(workdir, "list", "--shoe", "Left").returncode == 0
    assert run_tool(workdir, "suggest").returncode == 0
    assert run_tool(workdir, "suggest", "--shoe", "Right").returncode == 0
    assert run_tool(workdir, "--help").returncode == 0
    assert store_file(workdir).read_bytes() == before


def test_list_and_suggest_never_create_the_store(workdir):
    assert run_tool(workdir, "list").returncode == 0
    assert run_tool(workdir, "suggest").returncode == 0
    assert store_file(workdir).exists() is False


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def seed_mixed_history(workdir):
    readings = [
        ("Left", "4.0", "2024-03-02", None),
        ("Left", "6.0", "2024-04-11", None),
        ("Left", "9.5", "2024-05-04", "right cleat creaks at the top of the stroke"),
        ("Right", "3.0", "2024-03-20", None),
        ("Right", "3.5", "2024-04-25", "new pedal body fitted"),
    ]
    for shoe, angle, day, note in readings:
        args = ["--shoe", shoe, "--float", angle, "--date", day]
        if note:
            args += ["--note", note]
        assert add(workdir, *args).returncode == 0


def test_list_groups_per_shoe_with_summaries(workdir):
    seed_mixed_history(workdir)

    result = run_tool(workdir, "list")

    assert result.returncode == 0
    assert result.stderr == ""
    output = result.stdout

    left_block, right_block = output.split("Right", 1)
    assert "Left" in left_block
    assert "2024-03-02" in left_block
    assert "4.0" in left_block
    assert "2024-04-11" in left_block
    assert "6.0" in left_block
    assert "2024-05-04" in left_block
    assert "9.5" in left_block
    assert "count 3" in left_block
    assert "first 2024-03-02" in left_block
    assert "last 2024-05-04" in left_block
    assert "latest 9.5" in left_block

    assert "2024-03-20" in right_block
    assert "3.0" in right_block
    assert "2024-04-25" in right_block
    assert "3.5" in right_block
    assert "count 2" in right_block
    assert "first 2024-03-20" in right_block
    assert "last 2024-04-25" in right_block
    assert "latest 3.5" in right_block


def test_list_sorts_ascending_even_when_logged_out_of_order(workdir):
    for day, angle in (("2024-05-04", "9.5"), ("2024-03-02", "4.0"), ("2024-04-11", "6.0")):
        assert add(workdir, "--shoe", "Left", "--float", angle, "--date", day).returncode == 0

    result = run_tool(workdir, "list")
    dates = [line.strip()[:10] for line in result.stdout.splitlines() if line.strip()[:4].isdigit()]

    assert dates == ["2024-03-02", "2024-04-11", "2024-05-04"]


def test_list_keeps_insertion_order_for_equal_dates(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.0", "--date", "2024-05-04")
    add(workdir, "--shoe", "Left", "--float", "6.0", "--date", "2024-05-04")

    result = run_tool(workdir, "list")
    reading_lines = [line for line in result.stdout.splitlines() if line.strip().startswith("2024-05-04")]

    assert len(reading_lines) == 2
    assert "4.0" in reading_lines[0]
    assert "6.0" in reading_lines[1]


def test_list_shows_the_note_on_the_reading_line(workdir):
    seed_mixed_history(workdir)

    result = run_tool(workdir, "list")

    note_lines = [
        line for line in result.stdout.splitlines()
        if "right cleat creaks at the top of the stroke" in line
    ]
    assert len(note_lines) == 1
    line = note_lines[0]
    assert "2024-05-04" in line
    assert "9.5" in line


def test_list_shoe_filter_hides_the_other_shoe(workdir):
    seed_mixed_history(workdir)

    result = run_tool(workdir, "list", "--shoe", "Left")

    assert result.returncode == 0
    assert "Left" in result.stdout
    assert "count 3" in result.stdout
    assert "latest 9.5" in result.stdout
    assert "Right" not in result.stdout
    assert "2024-03-20" not in result.stdout
    assert "count 2" not in result.stdout


def test_list_shoe_filter_accepts_lower_case(workdir):
    seed_mixed_history(workdir)

    result = run_tool(workdir, "list", "--shoe", "right")

    assert result.returncode == 0
    assert "Right" in result.stdout
    assert "count 2" in result.stdout
    assert "Left" not in result.stdout


def test_list_rejects_an_unknown_shoe_filter(workdir):
    seed_mixed_history(workdir)

    result = run_tool(workdir, "list", "--shoe", "Middle")

    assert result.returncode == 1
    assert "Left" in result.stderr and "Right" in result.stderr
    assert result.stdout == ""


def test_list_empty_state_exits_zero_and_never_creates_the_store(workdir):
    result = run_tool(workdir, "list")

    assert result.returncode == 0
    assert "No readings logged yet" in result.stdout
    assert "python3 cleatstomp.py add --shoe Left --float 4.5" in result.stdout
    assert store_file(workdir).exists() is False


def test_list_empty_state_honours_the_shoe_filter(workdir):
    add(workdir, "--shoe", "Left", "--float", "4.5")

    result = run_tool(workdir, "list", "--shoe", "Right")

    assert result.returncode == 0
    assert "No readings logged yet for Right" in result.stdout
    assert "add --shoe Right" in result.stdout


def test_list_aligns_columns_across_twelve_readings(workdir):
    notes = {
        "2024-01-05": None,
        "2024-01-19": "cleat looks fine after the wet week in Girona",
        "2024-02-02": None,
        "2024-02-16": "slight rocking under load on the left side, worth watching",
        "2024-03-01": None,
        "2024-03-15": None,
        "2024-03-29": "swapped in the spare cleat bolts",
        "2024-04-12": None,
        "2024-04-26": None,
        "2024-05-10": "creak is back at the top of the stroke",
        "2024-05-24": None,
        "2024-06-07": None,
    }
    for index, (day, note) in enumerate(sorted(notes.items())):
        args = ["--shoe", "Left", "--float", str(4.0 + index * 0.5), "--date", day]
        if note:
            args += ["--note", note]
        assert add(workdir, *args).returncode == 0

    result = run_tool(workdir, "list")
    reading_lines = [line for line in result.stdout.splitlines() if line.strip()[:4].isdigit()]
    assert len(reading_lines) == 12

    angle_columns = {line.index("float") if "float" in line else -1 for line in reading_lines}
    assert angle_columns == {-1}

    header_note_offset = next(
        line.index("note") for line in result.stdout.splitlines() if line.strip().startswith("date")
    )
    note_columns = set()
    for line in reading_lines:
        for note in notes.values():
            if note and note in line:
                note_columns.add(line.index(note))
    assert len(note_columns) == 1
    assert note_columns.pop() == header_note_offset


# --------------------------------------------------------------------------- #
# suggest
# --------------------------------------------------------------------------- #


def single_reading(workdir, shoe, days, angle):
    assert add(workdir, "--shoe", shoe, "--float", str(angle), "--date", days_ago(days)).returncode == 0


@pytest.mark.parametrize("days", [90, 91, 120])
def test_suggest_recommends_replacement_at_or_past_the_interval(workdir, days):
    single_reading(workdir, "Left", days, 4.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    left_line = next(line for line in result.stdout.splitlines() if line.startswith("Left"))
    assert "REPLACE" in left_line
    assert "{} days".format(days) in result.stdout
    assert "90-day replacement interval" in result.stdout


@pytest.mark.parametrize("days,remaining", [(0, 90), (1, 89), (45, 45), (89, 1)])
def test_suggest_reports_days_remaining_inside_the_interval(workdir, days, remaining):
    single_reading(workdir, "Left", days, 4.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    left_line = next(line for line in result.stdout.splitlines() if line.startswith("Left"))
    assert "REPLACE" not in left_line
    assert "OK" in left_line
    assert "inside the 90-day interval" in left_line
    assert "{} day".format(remaining) in left_line


def test_suggest_flags_float_drift_inside_the_age_interval(workdir):
    single_reading(workdir, "Left", 30, 4.0)
    single_reading(workdir, "Left", 0, 13.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    left_line = next(line for line in result.stdout.splitlines() if line.startswith("Left"))
    assert "REPLACE" in left_line
    assert "9.0" in left_line
    assert "30 days" in left_line
    assert "past the 90-day replacement interval" not in result.stdout


def test_suggest_reports_a_rise_below_the_threshold(workdir):
    single_reading(workdir, "Left", 30, 4.0)
    single_reading(workdir, "Left", 0, 11.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    left_line = next(line for line in result.stdout.splitlines() if line.startswith("Left"))
    assert "REPLACE" not in left_line
    assert "7.0" in result.stdout
    assert "below the 8.0" in result.stdout


def test_suggest_reports_drift_from_a_thirty_one_day_old_reading_as_unmeasurable(workdir):
    single_reading(workdir, "Left", 31, 4.0)
    single_reading(workdir, "Left", 0, 20.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    assert "not yet measurable" in result.stdout
    assert "REPLACE" not in result.stdout


def test_suggest_reports_a_single_reading_as_not_yet_measurable(workdir):
    single_reading(workdir, "Left", 10, 4.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    assert "not yet measurable" in result.stdout
    assert "10 days" in result.stdout
    assert "80 days" in result.stdout


def test_suggest_mentions_both_rules_when_both_fire(workdir):
    single_reading(workdir, "Left", 100, 4.0)
    single_reading(workdir, "Left", 25, 4.0)
    single_reading(workdir, "Left", 0, 12.0)

    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    left_line = next(line for line in result.stdout.splitlines() if line.startswith("Left"))
    assert "REPLACE" in left_line
    assert "100 days" in left_line
    assert "8.0" in left_line


def test_suggest_covers_both_shoes_and_advises_one_with_the_filter(workdir):
    single_reading(workdir, "Left", 95, 4.0)
    single_reading(workdir, "Right", 5, 3.0)

    both = run_tool(workdir, "suggest")
    assert both.returncode == 0
    assert "Left" in both.stdout and "Right" in both.stdout

    filtered = run_tool(workdir, "suggest", "--shoe", "Left")
    assert filtered.returncode == 0
    assert filtered.stdout.startswith("Left")
    assert "Right" not in filtered.stdout


def test_suggest_empty_state_invites_a_reading(workdir):
    result = run_tool(workdir, "suggest")

    assert result.returncode == 0
    assert "Not enough data yet" in result.stdout
    assert "python3 cleatstomp.py add --shoe Left --float 4.0" in result.stdout
    assert store_file(workdir).exists() is False


def test_suggest_empty_state_for_a_filtered_shoe(workdir):
    single_reading(workdir, "Left", 100, 4.0)

    result = run_tool(workdir, "suggest", "--shoe", "Right")

    assert result.returncode == 0
    assert "No readings logged yet for Right" in result.stdout
    assert "python3 cleatstomp.py add --shoe Right --float 4.0" in result.stdout


def test_suggest_rejects_an_unknown_shoe_filter(workdir):
    result = run_tool(workdir, "suggest", "--shoe", "Both")

    assert result.returncode == 1
    assert "Left" in result.stderr and "Right" in result.stderr


# --------------------------------------------------------------------------- #
# Unit tests on the module itself
# --------------------------------------------------------------------------- #


def test_module_imports_without_side_effects():
    import cleatstomp

    assert cleatstomp.STORE_VERSION == 1
    assert cleatstomp.REPLACEMENT_DAYS == 90
    assert cleatstomp.DRIFT_THRESHOLD == 8.0
    assert cleatstomp.DRIFT_WINDOW_DAYS == 30
    assert cleatstomp.SHOES == ("Left", "Right")


def test_format_angle_keeps_at_least_one_decimal():
    import cleatstomp

    assert cleatstomp.format_angle(4.0) == "4.0\u00b0"
    assert cleatstomp.format_angle(4.5) == "4.5\u00b0"
    assert cleatstomp.format_angle(4.55) == "4.55\u00b0"
    assert cleatstomp.format_angle(0) == "0.0\u00b0"


def test_canonical_shoe_is_case_insensitive():
    import cleatstomp
    import pytest as _pytest

    assert cleatstomp.canonical_shoe("left") == "Left"
    assert cleatstomp.canonical_shoe(" RIGHT ") == "Right"
    with _pytest.raises(cleatstomp.CliError):
        cleatstomp.canonical_shoe("Middle")


def test_parse_float_angle_enforces_the_inclusive_range():
    import cleatstomp
    import pytest as _pytest

    assert cleatstomp.parse_float_angle("0") == 0.0
    assert cleatstomp.parse_float_angle("30") == 30.0
    for bad in ("-0.5", "30.5", "abc", "nan", "inf"):
        with _pytest.raises(cleatstomp.CliError):
            cleatstomp.parse_float_angle(bad)


def test_drift_window_is_thirty_days_inclusive():
    import cleatstomp

    today = date(2024, 6, 1)
    inside = [
        cleatstomp.Entry(shoe="Left", date="2024-05-02", float_angle=4.0),
        cleatstomp.Entry(shoe="Left", date="2024-06-01", float_angle=13.0),
    ]
    assert cleatstomp.drift_over_window(inside, today) == 9.0

    outside = [
        cleatstomp.Entry(shoe="Left", date="2024-05-01", float_angle=4.0),
        cleatstomp.Entry(shoe="Left", date="2024-06-01", float_angle=13.0),
    ]
    assert cleatstomp.drift_over_window(outside, today) is None


def test_summarise_derives_count_first_last_latest_and_remaining_days():
    import cleatstomp

    today = date(2024, 6, 1)
    entries = [
        cleatstomp.Entry(shoe="Left", date="2024-04-01", float_angle=4.0),
        cleatstomp.Entry(shoe="Left", date="2024-03-01", float_angle=3.0),
        cleatstomp.Entry(shoe="Right", date="2024-05-01", float_angle=9.0),
    ]

    summary = cleatstomp.summarise("Left", entries, today)

    assert summary.count == 2
    assert summary.first_date == "2024-03-01"
    assert summary.last_date == "2024-04-01"
    assert summary.latest_float == 4.0
    assert summary.days_since_first == 92
    assert summary.days_remaining == -2
    assert summary.replacement_due is True
    assert cleatstomp.summarise("Middle", entries, today) is None


def test_store_round_trip_through_the_atomic_writer(tmp_path):
    import cleatstomp

    target = str(tmp_path / "cleatstomp.json")
    entries = [
        cleatstomp.Entry(shoe="Left", date="2024-05-04", float_angle=4.5),
        cleatstomp.Entry(shoe="Right", date="2024-05-05", float_angle=6.0, note="new bolts"),
    ]

    cleatstomp.save_entries(target, entries)
    loaded = cleatstomp.load_entries(target)

    assert loaded == entries
    assert tmp_path.joinpath("cleatstomp.json").read_text(encoding="utf-8").startswith(
        '{\n  "version": 1'
    )
    assert [path.name for path in tmp_path.iterdir()] == ["cleatstomp.json"]


def test_load_entries_treats_a_missing_file_as_empty(tmp_path):
    import cleatstomp

    assert cleatstomp.load_entries(str(tmp_path / "missing.json")) == []


# --------------------------------------------------------------------------- #
# Shipped scripts
# --------------------------------------------------------------------------- #


def test_acceptance_harness_passes():
    argv = [sys.executable, str(ROOT / "acceptance_check.py")]
    result = subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "acceptance cases passed" in result.stdout
    assert "FAIL" not in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_demo_script_runs_clean_and_leaves_no_log_behind():
    argv = ["bash", str(ROOT / "demo.sh")]
    result = subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "REPLACE" in result.stdout and "OK" in result.stdout
    assert (ROOT / "cleatstomp.json").exists() is False
