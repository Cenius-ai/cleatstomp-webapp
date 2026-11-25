#!/usr/bin/env bash
# CleatStomp end-to-end demo.
#
# Seeds a throwaway wear log in a temporary directory and walks every command:
# add, list, suggest, the rejected-input guardrails, the malformed-file guard
# and --help. Non-interactive, no network, exits 0.
#
#   bash demo.sh          # or sh demo.sh
#
# The temporary directory is removed on exit, so your own ./cleatstomp.json is
# never touched. Set CLEATSTOMP_DEMO_DIR to keep the demo log somewhere.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
TOOL="$(pwd)/cleatstomp.py"

ACCENT=""
MUTED=""
RESET=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    ACCENT=$'\033[38;2;179;97;54m'
    MUTED=$'\033[38;2;150;145;137m'
    RESET=$'\033[0m'
fi

DEMO_DIR="${CLEATSTOMP_DEMO_DIR:-$(mktemp -d)}"
mkdir -p "$DEMO_DIR"
cleanup() {
    if [ -z "${CLEATSTOMP_DEMO_DIR:-}" ]; then rm -rf "$DEMO_DIR"; fi
}
trap cleanup EXIT
cd "$DEMO_DIR"

heading() {
    printf '\n%s\n' "${ACCENT}────────────────────────────────────────────────────────────${RESET}"
    printf '%s%s%s\n\n' "$ACCENT" "$1" "$RESET"
}

show() {
    printf '%s$ cleatstomp.py %s%s\n' "$MUTED" "$*" "$RESET"
    set +e
    "$PYTHON" "$TOOL" "$@"
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        printf '%s(exit %d)%s\n' "$MUTED" "$status" "$RESET"
    fi
}

day() {
    "$PYTHON" -c 'import datetime, sys; print((datetime.date.today() - datetime.timedelta(days=int(sys.argv[1]))).isoformat())' "$1"
}

printf '%sCleatStomp %s%s — demo session\n' "$ACCENT" "$("$PYTHON" "$TOOL" --version | awk '{print $2}')" "$RESET"
printf '%sWear log under %s (removed when the demo ends).%s\n' "$MUTED" "$DEMO_DIR" "$RESET"

heading "1. Usage — help first"
show --help

heading "2. Log readings — add"
show add --shoe Left --float 4.0 --date "$(day 95)" --note "baseline fit at the shop"
show add --shoe Left --float 4.5 --date "$(day 60)"
show add --shoe Left --float 5.0 --date "$(day 25)" --note "slight rocking under load"
show add --shoe left --float 12.5 --date "$(day 0)" --note "creak at the top of the stroke"
show add --shoe Right --float 3.0 --date "$(day 40)"
show add --shoe right --float 3.5 --date "$(day 5)" --note "new bolts torqued to 5 Nm"

heading "3. Wear history — list"
show list

heading "4. Wear history for one shoe — list --shoe Left"
show list --shoe Left

heading "5. Replacement advice — suggest"
show suggest

heading "6. Advice for one shoe — suggest --shoe Right"
show suggest --shoe Right

heading "7. Rejected input — nothing is written"
show add --shoe Middle --float 4.0
show add --shoe Left --float 42
show add --shoe Left --float abc
show add --shoe Left --float 4.0 --date 2024-02-30
show add --shoe Left --float

heading "8. Malformed log — reported, never rewritten"
cp cleatstomp.json cleatstomp.backup.json
printf '{oops' > cleatstomp.json
show list
printf '%sfile still holds exactly:%s ' "$MUTED" "$RESET"
cat cleatstomp.json
cp cleatstomp.backup.json cleatstomp.json
rm cleatstomp.backup.json

heading "9. The log itself — human-readable JSON, versioned"
cat cleatstomp.json

heading "Done — every command above ran offline in $DEMO_DIR"
printf '%sNext: run %spython3 cleatstomp.py --help%s in your own directory.%s\n' \
    "$MUTED" "$ACCENT" "$MUTED" "$RESET"
