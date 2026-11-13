#!/bin/sh
# Phase 23b: apply each production mutation to the worktree's src/fastpath.c, rebuild, run FastpathDifftest
# on 2000 seeds; every mutation must be detected. Restores fastpath.c and rebuilds at the end.
# Usage: run-mut.sh <worktree> <outdir>
set -u
WT=$1; OUT=$2
MUT=tests/difftest/mutate_f.py
GT="GTEST_CFLAGS=-isystem $HOME/.local/include"
GL="GTEST_LIBS=$HOME/.local/lib64/libgmock.a $HOME/.local/lib64/libgtest.a -lsystemd -lpthread"
mkdir -p "$OUT"
cd "$WT" || exit 2
rebuild() {
    (cd src && make -j12 > "$1" 2>&1) || return 1
    (cd src/unit && make -j12 valkey-unit-gtests "$GT" "$GL" >> "$1" 2>&1) || return 1
    return 0
}
for m in m1 m2 m3 m4; do
    git checkout -q src/fastpath.c
    if ! python3 "$MUT" $m > "$OUT/mut-$m-apply.log" 2>&1; then
        echo "$m: anchor failed"
        cat "$OUT/mut-$m-apply.log"
        continue
    fi
    if ! rebuild "$OUT/mut-$m-build.log"; then
        echo "$m: build failed"
        continue
    fi
    if DIFFTEST_SEEDS=2000 DIFFTEST_MAXFAIL=100000 ./src/unit/valkey-unit-gtests --gtest_filter='FastpathDifftest.LanesMatch*' > "$OUT/mut-$m-full.log" 2>&1; then
        echo "$m: test PASSED (mutation NOT detected)"
    else
        echo "$m: detected, $(grep -c 'executors differ' "$OUT/mut-$m-full.log") of 2000 seeds differ"
    fi
    head -c 300000 "$OUT/mut-$m-full.log" > "$OUT/mut-$m.log"
done
git checkout -q src/fastpath.c
if rebuild "$OUT/restore-build.log"; then echo "restored and rebuilt"; else echo "restore build FAILED"; fi
git status --short
