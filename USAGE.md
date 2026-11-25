# Using CleatStomp

Every example assumes you are in the directory that holds `cleatstomp.py`, and
that `./cleatstomp.json` is the wear log for one bike or one customer. Run
`python3 cleatstomp.py --help` for the same information without the prose.

## Log a reading

```bash
python3 cleatstomp.py add --shoe Left --float 4.5
```

```
Saved Left reading for 2026-11-25: float 4.5°
```

The date defaults to today. Give it explicitly when you are transcribing a shop
worksheet, and add a note when the reading needs context:

```bash
python3 cleatstomp.py add --shoe Right --float 6.25 --date 2026-10-16 \
    --note "creaks at the top of the stroke on the right pedal"
```

```
Saved Right reading for 2026-10-16: float 6.25° — note: creaks at the top of the stroke on the right pedal
```

`--shoe` accepts any casing (`left`, `RIGHT`) and is stored as `Left` / `Right`.
`--float` must be between 0.0 and 30.0 degrees inclusive; `--date` must be a real
calendar date in `YYYY-MM-DD` form; `--note` is optional free text.

### What happens when a reading is rejected

```bash
$ python3 cleatstomp.py add --shoe Middle --float 4.0
cleatstomp: error: --shoe must be Left or Right (got 'Middle'); accepted values: Left, Right

$ python3 cleatstomp.py add --shoe Left --float 42
cleatstomp: error: --float must be between 0.0 and 30.0 degrees (got '42')

$ python3 cleatstomp.py add --shoe Left --float abc
cleatstomp: error: --float must be a number between 0.0 and 30.0 degrees (got 'abc')

$ python3 cleatstomp.py add --shoe Left --float 4.0 --date 2024-02-30
cleatstomp: error: --date must be a real calendar date in YYYY-MM-DD format (got '2024-02-30')
```

Each of these exits `1` and leaves `cleatstomp.json` **byte-for-byte unchanged**
(and does not create it if it did not exist). A malformed flag — for example
`--float` with no value — is an argument-parser usage error and exits `2`.

## Read the history

```bash
python3 cleatstomp.py list
```

```
Left — 4 readings
  date        float  note
  2026-08-22  4.0°   baseline fit at the shop
  2026-09-26  4.5°
  2026-10-31  5.0°   slight rocking under load
  2026-11-25  12.5°  creak at the top of the stroke
  ────────────────────────────────────────────────────
  count 4 · first 2026-08-22 · last 2026-11-25 · latest 12.5°

Right — 2 readings
  date        float  note
  2026-10-16  3.0°
  2026-11-20  3.5°   new bolts torqued to 5 Nm
  ────────────────────────────────────────────────────
  count 2 · first 2026-10-16 · last 2026-11-20 · latest 3.5°
```

Readings are always printed in ascending date order, even when you logged them
out of order; readings that share a date keep the order you logged them in. One
shoe at a time:

```bash
python3 cleatstomp.py list --shoe Left
```

With no readings at all, `list` prints an invitation instead of an empty screen
and exits `0` without creating the data file:

```
No readings logged yet.

Log the first one:
  python3 cleatstomp.py add --shoe Left --float 4.5
```

## Get replacement advice

```bash
python3 cleatstomp.py suggest
```

```
Left   REPLACE cleat is 95 days old (first reading 2026-08-22) — past the 90-day replacement interval
       first reading 2026-08-22 (95 days ago) · latest 12.5° on 2026-11-25 · float rise 7.5° over the last 30 days (below the 8.0° threshold)
Right  OK      inside the 90-day interval — 50 days remaining
       first reading 2026-10-16 (40 days ago) · latest 3.5° on 2026-11-20 · float rise not yet measurable (needs two readings inside the last 30 days)
```

Two fixed rules decide the verdict:

| Rule | Threshold | How it is measured |
| --- | --- | --- |
| Age | 90 days | days from the shoe's earliest reading to today; `>= 90` recommends replacement |
| Float drift | 8.0 degrees | earliest-to-latest rise inside the trailing 30 days (inclusive); `>= 8.0` recommends replacement on its own |

A drift verdict names the rise so you can see which rule fired:

```
Left   REPLACE float rose 9.0° over the last 30 days — at or past the 8.0° float-drift threshold
       first reading 2026-10-26 (30 days ago) · latest 13.0° on 2026-11-25 · float rise 9.0° over the last 30 days (at or above the 8.0° threshold)
```

One shoe at a time:

```bash
python3 cleatstomp.py suggest --shoe Right
```

With nothing logged, `suggest` says so and shows the command to start with
(exit `0`):

```
Not enough data yet.

No readings logged yet, so there is nothing to advise on.
Log a reading and run suggest again:
  python3 cleatstomp.py add --shoe Left --float 4.0
```

## Scripting

Because output is line-oriented and deterministic, and errors go to stderr, the
tool composes with the usual shell tools:

```bash
# latest left reading
python3 cleatstomp.py list --shoe Left | grep -E '^  [0-9]{4}-' | tail -1

# is anything due?
python3 cleatstomp.py suggest | grep -q REPLACE && echo "order new cleats"
```

Exit codes: `0` success (including empty states), `1` validation or data-file
error, `2` argument-parser usage error.

## Common situations

| Situation | What to do |
| --- | --- |
| Logged the wrong angle | log a corrected reading with `add`; the history keeps both, which is honest wear data |
| `cleatstomp.json` was hand-edited into invalid JSON | the tool reports the path and exits `1` without touching it; fix the JSON or move the file aside |
| Two bikes | run the tool from two directories, one `cleatstomp.json` each |
| Long-term record | copy `cleatstomp.json` somewhere safe before editing it by hand, or keep a dated copy |
