#!/bin/sh
# Phase 23b: ASAN build of the test branch commit in a detached scratch worktree, then run the difftest
# (2000 seeds), FastpathLanesTest x20 and the 14-suite one-process set x3.
# Usage: build-asan.sh <commit> <outdir>
set -u
COMMIT=$1; OUT=$2
WT=$WORK/p23b/asan-wt
mkdir -p "$OUT"
git -C ${VALKEY_CLONE:-$HOME/valkey} worktree add --detach "$WT" "$COMMIT" > "$OUT/asan-wt.log" 2>&1 || exit 2
cd "$WT" || exit 2
taskset -c 8-15 make -j8 SANITIZER=address > "$OUT/asan-build.log" 2>&1 || { echo "EXIT $? (server)" >> "$OUT/asan-build.log"; exit 1; }
cd src/unit || exit 2
taskset -c 8-15 make -j8 SANITIZER=address valkey-unit-gtests \
    GTEST_CFLAGS="-isystem $HOME/.local/include" \
    GTEST_LIBS="$HOME/.local/lib64/libgmock.a $HOME/.local/lib64/libgtest.a -lsystemd -lpthread" >> "$OUT/asan-build.log" 2>&1 || { echo "EXIT $? (gtests)" >> "$OUT/asan-build.log"; exit 1; }
export LD_LIBRARY_PATH=$HOME/.local/lib/sanitizer-rt
export ASAN_OPTIONS=detect_leaks=0
DIFFTEST_SEEDS=2000 ./valkey-unit-gtests --gtest_filter='FastpathDifftest.*' > "$OUT/asan-difftest-2000.log" 2>&1
echo "asan difftest rc=$? asan_errors=$(grep -c 'ERROR: AddressSanitizer' "$OUT/asan-difftest-2000.log")"
./valkey-unit-gtests --gtest_filter='FastpathLanesTest.*' --gtest_shuffle --gtest_repeat=20 > "$OUT/asan-lanes-x20.log" 2>&1
echo "asan lanes rc=$? passed_iters=$(grep -c '^\[  PASSED  \]' "$OUT/asan-lanes-x20.log") asan_errors=$(grep -c 'ERROR: AddressSanitizer' "$OUT/asan-lanes-x20.log")"
F='FastpathExecutorTest.*:FastpathStagedTest.*:FastGetGatesTest.*:ReplApplyTest.*:ReplSenderTest.*:PollerTest.*:FastpathEntryTest.*:AclOffloadTest.*:ShutdownBoundTest.*:CommandOriginTest.*:ObjectTest.*:HashtableTest.*:FastpathLanesTest.*:FastpathDifftest.*'
DIFFTEST_SEEDS=200 RADIFF_SEEDS=300 timeout 1700 ./valkey-unit-gtests --gtest_shuffle --gtest_repeat=3 --gtest_filter="$F" > "$OUT/asan-multi-x3.log" 2>&1
echo "asan multi rc=$? passed_iters=$(grep -c '^\[  PASSED  \]' "$OUT/asan-multi-x3.log") fails=$(grep -c 'FAILED  \]' "$OUT/asan-multi-x3.log") asan_errors=$(grep -c 'ERROR: AddressSanitizer' "$OUT/asan-multi-x3.log")"
grep -m1 'tests from .* ran' "$OUT/asan-multi-x3.log"
echo asan-done
