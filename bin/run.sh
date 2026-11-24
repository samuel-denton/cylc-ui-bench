#!/usr/bin/env bash
# Benchmark the cylc-ui workflows store across git refs.
#
# Each ref is checked out into a temporary git worktree under ~/.cache/cylc-ui-bench
# (or $BENCH_TMP), sharing node_modules with the main checkout. Rounds alternate the
# ref order (ABBA...) so machine noise is spread evenly, and every run appends
# to one JSONL results file, which is summarised at the end.
#
# Usage: run.sh [-C CYLC_UI_DIR] [-r ROUNDS] [-o RESULTS.jsonl] [-f] [-k] [REF...]
#   -C  cylc-ui checkout (default $CYLC_UI, else ../cylc-ui next to this repo)
#   -r  number of rounds (default 3)
#   -o  results file (default $BENCH_RESULTS/<timestamp>.jsonl,
#       where BENCH_RESULTS defaults to results/ in this repo)
#   -f  git fetch --all before resolving refs
#   -k  keep the worktrees afterwards
#   REF defaults to: master HEAD (the first ref is the baseline)
#
# Scale and scenario selection pass through as env vars, e.g.
#   BENCH_CYCLES=20 BENCH_TASKS=1000 BENCH_ITERATIONS=30 BENCH_ONLY='prune|spawn' ./run.sh -r 6
# Requires node/npx on PATH.
set -euo pipefail

BENCH_HOME=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SUITE_DIR=$BENCH_HOME/suites/store

usage () { awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "$0"; }

REPO=${CYLC_UI:-}
ROUNDS=3
RESULTS=
FETCH=false
KEEP=false
while getopts 'C:r:o:fkh' opt; do
  case $opt in
    C) REPO=$OPTARG ;;
    r) ROUNDS=$OPTARG ;;
    o) RESULTS=$OPTARG ;;
    f) FETCH=true ;;
    k) KEEP=true ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))
REFS=("$@")
[[ ${#REFS[@]} -gt 0 ]] || REFS=(master HEAD)

if [[ -z $REPO && -d $BENCH_HOME/../cylc-ui ]]; then REPO=$BENCH_HOME/../cylc-ui; fi
[[ -n $REPO ]] || { echo 'cylc-ui checkout not found: use -C DIR or set $CYLC_UI' >&2; exit 1; }
REPO=$(cd "$REPO" && pwd)
command -v npx >/dev/null || { echo 'npx not found on PATH' >&2; exit 1; }
[[ -d $REPO/node_modules ]] || { echo "no node_modules in $REPO (run yarn install)" >&2; exit 1; }

RESULTS_DIR=${BENCH_RESULTS:-$BENCH_HOME/results}
mkdir -p "$RESULTS_DIR"
RESULTS=$(realpath -m "${RESULTS:-$RESULTS_DIR/$(date +%Y%m%d-%H%M%S).jsonl}")
LOG=${RESULTS%.jsonl}.log

$FETCH && git -C "$REPO" fetch --all --quiet

# outside the VS Code workspace, so its git extension/file watcher leave them alone
TMP_BASE=${BENCH_TMP:-$HOME/.cache/cylc-ui-bench}
mkdir -p "$TMP_BASE"
WORK=$(mktemp -d "$TMP_BASE/run.XXXXXX")
declare -A DIRS LABELS
cleanup () {
  $KEEP && { echo "worktrees kept in $WORK"; return; }
  for dir in "${DIRS[@]}"; do rm -f "$dir/node_modules"; done  # the symlinks only
  # on NFS, recently closed files can block removal for a few seconds
  for _ in 1 2 3 4 5 6; do
    if [[ $WORK == "$TMP_BASE/run."* ]]; then rm -rf "$WORK" 2>/dev/null || true; fi
    git -C "$REPO" worktree prune 2>/dev/null || true
    if [[ ! -e $WORK ]] && ! git -C "$REPO" worktree list | grep -qF "$WORK"; then return; fi
    sleep 5
  done
  echo "WARNING: could not fully clean up $WORK" >&2
}
trap cleanup EXIT

for ref in "${REFS[@]}"; do
  sha=$(git -C "$REPO" rev-parse --verify --quiet "$ref^{commit}") || { echo "unknown ref: $ref" >&2; exit 1; }
  dir=$WORK/${ref//\//_}
  git -C "$REPO" worktree add --detach --quiet "$dir" "$sha"
  ln -s "$REPO/node_modules" "$dir/node_modules"
  mkdir -p "$dir/tests/unit/_bench"
  cp "$SUITE_DIR/deltas.js" "$SUITE_DIR/store.bench.spec.js" "$dir/tests/unit/_bench/"
  DIRS[$ref]=$dir
  LABELS[$ref]=$ref@${sha:0:8}
done

echo "results: $RESULTS"
echo "log:     $LOG"
failures=0
for round in $(seq 1 "$ROUNDS"); do
  order=("${REFS[@]}")
  if (( round % 2 == 0 )); then
    order=()
    for (( i = ${#REFS[@]} - 1; i >= 0; i-- )); do order+=("${REFS[i]}"); done
  fi
  for ref in "${order[@]}"; do
    echo "=== round $round/$ROUNDS: ${LABELS[$ref]} ($(date +%H:%M:%S))" | tee -a "$LOG"
    if ! (cd "${DIRS[$ref]}" && \
        NODE_ENV=production NO_COLOR=1 NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--expose-gc" \
        BENCH_LABEL=${LABELS[$ref]} BENCH_ROUND=$round BENCH_OUT=$RESULTS \
        npx vitest run tests/unit/_bench/ --silent=false >>"$LOG" 2>&1); then
      echo "    FAILED (see log)" | tee -a "$LOG"
      failures=$((failures + 1))
    fi
  done
done

[[ -s $RESULTS ]] && python3 "$BENCH_HOME/report/summarise.py" "$RESULTS" | tee -a "$LOG"
(( failures == 0 )) || { echo "$failures run(s) failed" >&2; exit 1; }
