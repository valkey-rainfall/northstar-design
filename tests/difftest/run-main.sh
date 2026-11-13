#!/bin/sh
# Phase 23b: the differential test at F (commit 6ba80d232 on 8cbc82360).
# Usage: run-main.sh <worktree> <outdir>
set -u
WT=$1; OUT=$2
B=$WT/src/unit/valkey-unit-gtests
mkdir -p "$OUT"
cd "$WT/src/unit" || exit 2
git -C "$WT" rev-parse HEAD > "$OUT/HEAD.sha"

# 1. seeds 1..2000, four executors compared
DIFFTEST_SEEDS=2000 $B --gtest_filter='FastpathDifftest.*' > "$OUT/run-seeds-1-2000.log" 2>&1 && echo "seeds 1..2000: PASS" || echo "seeds 1..2000: FAIL"

# 2. 20 repeats, fresh process, new seed range of 2000 each, shuffled test order
pass=0
for i in $(seq 1 20); do
    if DIFFTEST_SEEDS=2000 DIFFTEST_FIRST=$((i * 2000 + 1)) $B --gtest_filter='FastpathDifftest.*' --gtest_shuffle > "$OUT/run-repeat-$i.log" 2>&1; then pass=$((pass + 1)); fi
done
echo "20 repeats: $pass passed"

# 3. FastpathLanesTest, shuffled, 20 repeats in one process
$B --gtest_filter='FastpathLanesTest.*' --gtest_shuffle --gtest_repeat=20 > "$OUT/lanes-shuffle-x20.log" 2>&1 && echo "lanes x20: PASS" || echo "lanes x20: FAIL"

# 4. the Phase 22 one-process set plus the two new suites, shuffled, 20 repeats (difftest at 200 seeds per iteration)
F='FastpathExecutorTest.*:FastpathStagedTest.*:FastGetGatesTest.*:ReplApplyTest.*:ReplSenderTest.*:PollerTest.*:FastpathEntryTest.*:AclOffloadTest.*:ShutdownBoundTest.*:CommandOriginTest.*:ObjectTest.*:HashtableTest.*:FastpathLanesTest.*:FastpathDifftest.*'
DIFFTEST_SEEDS=200 RADIFF_SEEDS=300 $B --gtest_filter="$F" --gtest_shuffle --gtest_repeat=20 > "$OUT/multi-shuffle-x20.log" 2>&1 && echo "multi x20: PASS" || echo "multi x20: FAIL"
grep -c '^\[  PASSED  \]' "$OUT/multi-shuffle-x20.log"
echo done
