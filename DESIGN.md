# CleatStomp design source of truth

This is the committed design direction for CleatStomp. It is a terminal tool, so
"design" means the palette printed to a TTY, the character grid, the output
skeleton and the wording rules. Every screen the tool prints follows it.

## Archetype and style family

- **Archetype:** cli — a terminal program, not a web app. Proof is a transcript,
  not a screenshot.
- **Style family:** calm-precise. Few words, exact numbers, no exclamation marks,
  no emoji, no decorative rules longer than the content.
- **Density:** compact — one reading per line, no blank line between readings,
  one blank line between shoe sections.

## Tokens

| Token | Value | Used for |
| --- | --- | --- |
| Accent | `oklch(0.58 0.12 47)` — `#b36136` | section headings, the `REPLACE` verdict, demo script headings |
| Accent ANSI (truecolor) | `\x1b[38;2;179;97;54m` | the accent above, in a terminal |
| Primary text | `#e9e5de` (`\x1b[38;2;233;229;222m`) | reading lines, confirmations |
| Secondary text | `#969189` (`\x1b[38;2;150;145;137m`) | column headers, separators, evidence lines, `$` prompts |
| Separator | `─` (U+2500), 52 columns | the rule under each shoe's readings |
| Field separator | ` · ` (middle dot) | items inside a summary or evidence line |
| Em dash | `—` (U+2014) | the one place a sentence break is allowed inside a line |

Colour is **never the only signal**: `REPLACE` / `OK` are words, the drift verdict
says "at or above" / "below" in text, and the age verdict names the day count.
Colour is emitted only when stdout is a TTY, and never when `NO_COLOR` is set or
`--no-color` is passed — piped, redirected and captured output is byte-clean and
diffable.

The hex value exists for non-CSS contexts that cannot parse `oklch()`; the
terminal uses the truecolor ANSI form of the same colour.

## Type

System monospace, whatever the terminal is configured with. CleatStomp ships no
font, loads no remote font and has no way to choose one — that is the honest
terminal default, and it keeps the tool fully offline. All output is UTF-8;
degree signs (`°`), middle dots and box-drawing characters degrade to their ASCII
equivalents in a `TERM=dumb` terminal.

## Layout skeleton (committed; do not replace with another shape)

```
<command> <flags>          <- the command you typed (demo script prints it)
<result lines>             <- aligned columns, one record per line
────────────────────────── <- box-drawing separator (52 cols)
<summary>                  <- count · first · last · latest
```

- **Help first.** `--help` is the front door: description, `add` / `list` /
  `suggest`, the 0.0–30.0 range, the 90-day interval, the 8.0-degree threshold
  and one copy-pasteable example per command. A bare invocation prints the same
  help plus a "Start here:" hint and exits `0`.
- **Aligned columns.** `list` renders `date` (10 chars) · `float` (width of the
  widest angle in the run) · `note`, so every row reads as one table row and no
  note starts mid-column. `suggest` renders shoe (6) · verdict (7) · reason, then
  an indented evidence line.
- **Shape language.** Monospace, no chrome, box-drawing separators; the same
  separator + summary pairing on every shoe section.

## Wording rules

- Every confirmation names the shoe, the saved date, the angle and the note
  when one was given, in that order: `Saved Left reading for 2026-08-22: float 4.5° — note: baseline fit at the shop`.
- Every error goes to stderr as `cleatstomp: error: <what failed and how to fix it>`,
  with an optional `cleatstomp: hint:` line; exit `1`.
- Empty states always tell you the next command, copy-pasteable:
  `python3 cleatstomp.py add --shoe Left --float 4.5`.
- Numbers are printed with at least one decimal (`4.0°`, `4.5°`, `12.5°`); days
  are pluralised properly (`1 day`, `95 days`).
- No filler, no "Item 1", no lorem ipsum: seeded demo notes are real
  maintenance observations.

## Screens (terminal surfaces)

| Surface | Content | States |
| --- | --- | --- |
| `add` confirmation | `Saved <Shoe> reading for <date>: float <angle>° — note: <note>` | empty (rejection: one error line, nonzero exit, file untouched), populated |
| `list` history | `Left` / `Right` sections, aligned readings in date order, separator, summary | empty (invitation + add example, exit 0, no file created), populated, error (malformed file named by path, exit 1) |
| `suggest` advice | shoe · `REPLACE`/`OK` · reason, indented evidence line | empty (not-enough-data + add hint, exit 0), populated, error (malformed file, exit 1) |
| `--help` | usage, flags, thresholds, examples | populated (static text) |

## Accessibility and honesty floor

- No colour-only signal, no spinners, no fake progress, no splash.
- Identical record structure everywhere; nothing printed that does nothing.
- Text output is complete without colour and without a TTY.
- Every rejection is actionable and never destroys data.
