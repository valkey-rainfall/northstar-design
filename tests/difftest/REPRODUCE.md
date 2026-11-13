# REPRODUCE: Phase 23b, the lane differential test at F

Revision: valkey-rainfall/valkey commit 6ba80d232, one commit on
8cbc8236017d4e6e16264cffb37e664a4c1854df (PRFIX = F f01d005ea plus our 29 commits).
Host used: x86_64 Linux, gcc 11.5, make, python3; googletest 1.15 under $HOME/.local (lib64/libgmock.a,
lib64/libgtest.a, include/); libsystemd. ${R} is this folder (tests/difftest).

## 1. Worktree and build

    git -C <clone of valkey-rainfall/valkey> fetch origin 6ba80d232  # by commit id; use the full id if the remote asks
    git -C <clone> worktree add --detach <wt> 6ba80d232
    make -C <wt> -j8 && make -C <wt>/src/unit -j8 valkey-unit-gtests GTEST_CFLAGS=... GTEST_LIBS=...   # as in build-asan.sh, without SANITIZER

Or apply ${R}/0001-test-port-difftest.patch onto 8cbc82360 with `git am`.

## 2. The runs (scripts in this folder; expected results in STATUS.md)

    sh ${R}/run-main.sh <wt> <outdir>       # 2000 seeds, 20 shuffled repeats (42,000 seeds), lanes x20, 14 suites x20
    sh ${R}/run-mut.sh <wt> <outdir>        # m1..m4 through mutate_f.py: each must be detected; restores fastpath.c
    sh ${R}/build-asan.sh 6ba80d232 <outdir>  # ASAN worktree under $WORK/p23b/asan-wt, three runs

Single seed replay (prints the program, the keys with their lane and shard, all four reply streams and
dumps): `DIFFTEST_SEED=<n> ./src/unit/valkey-unit-gtests --gtest_filter='FastpathDifftest.LanesMatch*'`.
Knobs: DIFFTEST_SEEDS (default 2000), DIFFTEST_FIRST, DIFFTEST_MAXFAIL (default 3).

## 3. The window probe (not committed)

    sed -n 592,688p <test_fastpath_lanes.cpp of 91dbb9c3> >> <wt>/src/unit/test_fastpath_lanes.cpp
    make -C <wt>/src/unit valkey-unit-gtests GTEST_CFLAGS=... GTEST_LIBS=...
    ./valkey-unit-gtests --gtest_filter='FastpathLanesTest.*InTheWindow*'   # expected: both FAIL (STATUS.md)
    git -C <wt> checkout src/unit/test_fastpath_lanes.cpp

`git show 91dbb9c3:src/unit/test_fastpath_lanes.cpp` gives the FIX file; lines 592-688 are newMainClient,
runOnMain, mainReply and the two tests.

## 4. Checks

    LC_ALL=C grep -nP '[^\x20-\x7E\t]' ${R}/*.md ${R}/*.py ${R}/*.sh ${R}/logs/*.txt ${R}/logs/*.log   # expected: no output
