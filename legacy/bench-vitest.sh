#!/usr/bin/env bash
# Benchmark the cylc-ui vitest unit suite.
#
# Runs one warmup then N timed runs, capturing both wall-clock time and
# vitest's own Duration breakdown (which isolates the DOM-environment cost:
# the thing PR #2665 changes by swapping jsdom -> happy-dom).
#
# Results are printed to the terminal AND appended to a results file, with a
# timestamped marker per invocation so master and PR-branch runs accumulate
# together for easy comparison.
#
# Usage: ./bench-vitest.sh [N_RUNS] [REPO_DIR] [RESULTS_FILE]
set -euo pipefail

N=${1:-5}
REPO=${2:-/home/users/samuel.denton/cylc-dev/cylc-ui}
RESULTS=${3:-/home/users/samuel.denton/cylc-dev/bench-vitest-results.txt}

cd "$REPO"

label=$(git rev-parse --short HEAD)
branch=$(git rev-parse --abbrev-ref HEAD)

# log: print to terminal and append to the results file.
log() { printf '%s\n' "$*" | tee -a "$RESULTS"; }

log "======================================================================"
log "=== vitest benchmark @ $(date '+%Y-%m-%d %H:%M:%S') ==="
log "repo:   $REPO"
log "branch: $branch ($label)"
log "runs:   $N (+1 warmup)"
log ""

run_once() {
  # Emit the raw vitest Duration line, e.g.
  #   Duration  14.32s (environment 70%, transform 12%, import 6%, tests 2%)
  # NO_COLOR disables ANSI codes so the line parses cleanly.
  NO_COLOR=1 yarn run test:unit --run 2>&1 | grep -a Duration
}

echo "warmup..."
run_once >/dev/null 2>&1 || true

declare -a totals=()
declare -a envpcts=()

for i in $(seq 1 "$N"); do
  line=$(run_once)
  total=$(sed -E 's/.*Duration[[:space:]]+([0-9.]+)s.*/\1/' <<<"$line")
  envpct=$(sed -E 's/.*environment ([0-9]+)%.*/\1/' <<<"$line")
  totals+=("$total")
  envpcts+=("$envpct")
  log "$(printf 'run %d: total=%ss  environment=%s%%' "$i" "$total" "$envpct")"
done

# mean / stddev of totals
summary=$(python - "${totals[@]}" <<'PY'
import sys, statistics
xs = [float(x) for x in sys.argv[1:]]
mean = statistics.mean(xs)
sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
print(f"total wall time: mean {mean:.2f}s  sd {sd:.2f}s  min {min(xs):.2f}s  max {max(xs):.2f}s")
PY
)
log ""
log "$summary"
log ""
