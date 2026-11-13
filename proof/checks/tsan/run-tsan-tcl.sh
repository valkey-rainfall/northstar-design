#!/bin/sh
# Item 3: run the lane, MAINT-lane and replica apply Tcl suites against the TSan build of the branch.
# Usage: run-tsan-tcl.sh <tsan-worktree> <outdir> [suites...]
# TSan reports go to <outdir>/tsan.<pid> (log_path); the test framework's own output to <outdir>/runtest.log.
set -u
WT=$1; OUT=$2; shift 2
SUITES=${*:-"--single unit/staged-loop-lanes --single unit/maint-lanes --single integration/replica-parallel-apply"}
mkdir -p "$OUT"
export LD_LIBRARY_PATH=$HOME/.local/lib/sanitizer-rt
SUPP=$WT/ev/tsan.supp
[ -f "$SUPP" ] || SUPP=/dev/null
export TSAN_OPTIONS="halt_on_error=0 report_signal_unsafe=0 second_deadlock_stack=1 log_path=$OUT/tsan suppressions=$SUPP history_size=4"
cd "$WT" || exit 2
# shellcheck disable=SC2086
timeout 3000 ./runtest $SUITES --clients 1 --timeout 600 > "$OUT/runtest.log" 2>&1
echo "runtest exit=$?" >> "$OUT/runtest.log"
grep -c '\[ok\]' "$OUT/runtest.log"
grep -n '\[err\]\|exception\|All tests passed' "$OUT/runtest.log" | head -5
echo "TSan report files: $(ls "$OUT"/tsan.* 2>/dev/null | wc -l); warnings: $(cat "$OUT"/tsan.* 2>/dev/null | grep -c 'WARNING: ThreadSanitizer')"
