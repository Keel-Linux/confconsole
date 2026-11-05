#!/bin/bash -eu

# Runs the bats tests under kcov and fails when a measured file is below
# COVERAGE_THRESHOLD percent of executed lines (default 100, the number
# measured when the first bats test landed).
#
# usage: tests/coverage.sh [OUTDIR]
#
# Needs bats and kcov. Only the shell files under share/ are measured; the
# Python modules are measured by coverage.py (.forgejo/workflows/tests.yml).

THRESHOLD=${COVERAGE_THRESHOLD:-100}
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUTDIR=${1:-$REPO/coverage}

rm -rf "$OUTDIR"
kcov --include-path="$REPO/share" \
    --exclude-path="$REPO/tests" \
    "$OUTDIR" bats "$REPO/tests"

REPORT=$(find "$OUTDIR" -path '*/bats.*/coverage.json' | head -1)
if [[ -z "$REPORT" ]]; then
    echo "coverage.sh: no coverage.json under $OUTDIR" >&2
    exit 1
fi

# kcov writes one file per line:
#   {"file": "PATH", "percent_covered": "P", "covered_lines": "C", "total_lines": "T"},
echo
echo "kcov line coverage (threshold $THRESHOLD percent):"
awk -F'"' -v threshold="$THRESHOLD" -v repo="$REPO/" '
    /^ *\{"file":/ {
        file = $4
        sub(repo, "", file)
        percent = $8 + 0
        mark = (percent >= threshold) ? "ok" : "BELOW THRESHOLD"
        if (percent < threshold) {
            low = 1
        }
        files++
        printf "%7.2f  %4s/%-4s  %-32s %s\n", percent, $12, $16, file, mark
    }
    /^  "percent_covered":/ {
        printf "%7.2f  total\n", $4 + 0
    }
    END {
        if (files == 0) {
            print "coverage.sh: kcov measured no file" > "/dev/stderr"
            exit 1
        }
        exit low
    }' "$REPORT"
