#!/usr/bin/env bash
# Run run.sh in several sessions spread out over time (e.g. overnight) at one or
# more workflow scales, then write text and markdown summaries per scale.
#
# Usage: overnight.sh [-C CYLC_UI_DIR] [-n SESSIONS] [-r ROUNDS] [-d DELAY_MIN] [-s SCALES] [REF...]
#   -C  cylc-ui checkout, passed to run.sh
#   -n  number of sessions (default 4)
#   -r  rounds per session, per scale (default 2)
#   -d  minutes to wait between sessions (default 30)
#   -s  space-separated CYCLESxTASKSxJOBS scales (default "10x500x2 2x2500x2")
#   REF passed to run.sh (default: master HEAD)
#
# To keep it running after logging out:
#   nohup ./overnight.sh > overnight.out 2>&1 &
# Results go to $BENCH_RESULTS/overnight-<timestamp>/ (<scale>.jsonl/.log,
# summary.txt/.md, report.html), where BENCH_RESULTS defaults to results/ in this repo.
set -euo pipefail

BENCH_HOME=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage () { awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "$0"; }

RUN_ARGS=()
SESSIONS=4
ROUNDS=2
DELAY=30
SCALES='10x500x2 2x2500x2'
while getopts 'C:n:r:d:s:h' opt; do
  case $opt in
    C) RUN_ARGS+=(-C "$OPTARG") ;;
    n) SESSIONS=$OPTARG ;;
    r) ROUNDS=$OPTARG ;;
    d) DELAY=$OPTARG ;;
    s) SCALES=$OPTARG ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

OUT=${BENCH_RESULTS:-$BENCH_HOME/results}/overnight-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
echo "results: $OUT"

for session in $(seq 1 "$SESSIONS"); do
  for scale in $SCALES; do
    IFS=x read -r cycles tasks jobs <<<"$scale"
    echo "### session $session/$SESSIONS, scale $scale ($(date '+%F %T'))"
    BENCH_CYCLES=$cycles BENCH_TASKS=$tasks BENCH_JOBS=$jobs \
      "$BENCH_HOME/bin/run.sh" ${RUN_ARGS[@]+"${RUN_ARGS[@]}"} -r "$ROUNDS" -o "$OUT/$scale.jsonl" "$@" \
      || echo "    some runs failed, see $OUT/$scale.log"
  done
  if (( session < SESSIONS )); then
    echo "### sleeping ${DELAY}m"
    sleep "${DELAY}m"
  fi
done

for scale in $SCALES; do
  [[ -s $OUT/$scale.jsonl ]] || continue
  python3 "$BENCH_HOME/report/summarise.py" "$OUT/$scale.jsonl" >> "$OUT/summary.txt"
  python3 "$BENCH_HOME/report/summarise.py" --markdown "$OUT/$scale.jsonl" >> "$OUT/summary.md"
done
python3 "$BENCH_HOME/report/report.py" "$OUT"/*.jsonl > "$OUT/report.html"
echo "### done ($(date '+%F %T')), report: $OUT/report.html"
cat "$OUT/summary.txt"
