#!/bin/sh
# Phase 23d: the lane differential test on ceaa1101d plus our three test-seam commits (scratch, not pushed).
# Usage: run-dt.sh <worktree> <outdir>
set -u
WT=$1; OUT=$2
B=$WT/src/unit/valkey-unit-gtests
mkdir -p "$OUT"
cd "$WT/src/unit" || exit 2
git -C "$WT" log --oneline -4 > "$OUT/HEAD.txt"
DIFFTEST_SEEDS=2000 taskset -c 0-7 $B --gtest_filter='FastpathDifftest.*' > "$OUT/run-seeds-1-2000.log" 2>&1 && echo "seeds 1..2000: PASS" || echo "seeds 1..2000: FAIL"
pass=0
for i in $(seq 1 20); do
    if DIFFTEST_SEEDS=2000 DIFFTEST_FIRST=$((i * 2000 + 1)) taskset -c 0-7 $B --gtest_filter='FastpathDifftest.*' --gtest_shuffle > "$OUT/run-repeat-$i.log" 2>&1; then pass=$((pass + 1)); fi
done
echo "20 repeats: $pass passed"
taskset -c 0-7 $B --gtest_filter='FastpathLanesTest.*' --gtest_shuffle --gtest_repeat=20 > "$OUT/lanes-shuffle-x20.log" 2>&1 && echo "lanes x20: PASS" || echo "lanes x20: FAIL"
F='FastpathExecutorTest.*:FastpathStagedTest.*:ReplApplyTest.*:PollerTest.*:FastpathEntryTest.*:AclOffloadTest.*:CommandOriginTest.*:ObjectTest.*:HashtableTest.*:FastpathLanesTest.*:FastpathDifftest.*'
DIFFTEST_SEEDS=200 RADIFF_SEEDS=300 taskset -c 0-7 $B --gtest_filter="$F" --gtest_shuffle --gtest_repeat=10 > "$OUT/multi-shuffle-x10.log" 2>&1 && echo "multi x10: PASS" || echo "multi x10: FAIL"
grep -m1 'tests from .* ran' "$OUT/multi-shuffle-x10.log"
echo done
