# REPRODUCE: the proof checks on C

Revision: valkey-rainfall/valkey `northstar/proof-checks` = 8a1e6c1b4, eight commits on
C = ceaa1101d (patches/0001..0008 apply with `git am` onto C). Host: x86_64 Linux, gcc 11.5,
googletest 1.15 under $G (lib64/libgmock.a, libgtest.a, include/), libsystemd, tclsh;
libtsan.so.0 under $T (gcc 11 runtime, the host lacks it). ${R} is this folder.

## 1. Worktrees

    git -C <clone> fetch origin northstar/proof-checks
    git -C <clone> worktree add --detach <wt> origin/northstar/proof-checks

## 2. Build with the checks (about 2 minutes with -j8), then the unit binary

    cd <wt>
    make -j8 STAGED_CHECKS=yes
    make -j8 -C src/unit valkey-unit-gtests STAGED_CHECKS=yes \
        GTEST_CFLAGS="-isystem $G/include" GTEST_LIBS="$G/lib64/libgmock.a $G/lib64/libgtest.a -lpthread -lsystemd"

`make STAGED_CHECKS=yes` persists in src/.make-settings; `make distclean` to go back to a release build.

## 3. Items 4 and 5 (expected: 2 tests PASS)

    ./src/unit/valkey-unit-gtests --gtest_filter='FastpathListsTest.*'

Mutations (expected: the test FAILS; restore with `git checkout src/fastpath.c`):

    git apply ${R}/mutations/mut-4a-sort-on-allowlist.patch        # 5 failures: sort specs 1, 2 unknown; 125 entries
    git apply ${R}/mutations/mut-5a-blocking-not-denied.patch      # 31 failures: BLPOP and friends accepted

(rebuild the unit binary between mutations with the make -C src/unit line of step 2)

## 4. Item 1 (expected: 35 tests ok)

    ./runtest --single unit/staged-loop-lanes --clients 1

Mutations (expected: the server aborts with the named assertion in its log; the suite reports [err]):

    python3 ${R}/mutations/mut-1a.py && make -j8 STAGED_CHECKS=yes && ./runtest --single unit/staged-loop-lanes --clients 1
        # server.c: '!fastpathWindowOpen() || c->flag.executor || c->flag.reexecuting_command' on the first main-path command
    git checkout src/staged_loop.c
    python3 ${R}/mutations/mut-1b.py && make -j8 STAGED_CHECKS=yes && ./runtest --single unit/staged-loop-lanes --clients 1
        # fastpath.c: '!dictFind(e->db->blocking_keys, k) && !dictFind(e->db->watched_keys, k)' in the blocked-client test
    git checkout src/fastpath.c

## 5. Item 2 (expected: 55 tests ok; difftest PASS; lanes x5 PASS; ReplApplyTest PASS)

    ./runtest --single unit/staged-loop-lanes --single unit/maint-lanes --single integration/replica-parallel-apply --clients 2
    DIFFTEST_SEEDS=2000 ./src/unit/valkey-unit-gtests --gtest_filter='FastpathDifftest.*'
    ./src/unit/valkey-unit-gtests --gtest_filter='FastpathLanesTest.*' --gtest_shuffle --gtest_repeat=5
    RADIFF_SEEDS=300 ./src/unit/valkey-unit-gtests --gtest_filter='ReplApplyTest.*'

Mutations (expected: kvstore.c assertion '(kvs_owned_mod > 0 && didx % kvs_owned_mod == kvs_owned_lane) || didx == kvs_owned_only'):

    python3 ${R}/mutations/mut-2a.py && make -j8 STAGED_CHECKS=yes && ./runtest --single unit/staged-loop-lanes --clients 1
        # fires at "MSET and MGET across shards"; the difftest (DIFFTEST_MAXFAIL=100000) aborts at the first seed
    git checkout src/fastpath.c
    python3 ${R}/mutations/mut-2b.py && make -j8 STAGED_CHECKS=yes && ./runtest --single unit/staged-loop-lanes --clients 1
        # fires at the first lane entry
    git checkout src/fastpath.c

## 6. Item 3, TSan (about 3 minutes to build, 10 to run)

    git -C <clone> worktree add --detach <wt-tsan> origin/northstar/proof-checks
    cd <wt-tsan> && make -j8 SANITIZER=thread MALLOC=libc STAGED_CHECKS=yes
    make -j8 -C src/unit valkey-unit-gtests SANITIZER=thread MALLOC=libc STAGED_CHECKS=yes MORE_WARNINGS=-Wno-error \
        GTEST_CFLAGS="-isystem $G/include" GTEST_LIBS="$G/lib64/libgmock.a $G/lib64/libgtest.a -lpthread -lsystemd"
    # Tcl suites (expected: 55 ok, 0 TSan report files); edit LD_LIBRARY_PATH in the script to $T
    sh ${R}/tsan/run-tsan-tcl.sh <wt-tsan> <outdir>
    # extra suites (expected: 43 ok; 22 reports without the suppression file, all in tsan/tsan.supp classes;
    # with the file copied to <wt-tsan>/ev/tsan.supp: 0 beyond K1 inlined into fastGetTouch and G5/G6)
    sh ${R}/tsan/run-tsan-tcl.sh <wt-tsan> <outdir2> --single unit/fastget-correctness --single unit/fastpath-speculation --single unit/staged-loop-stress --single unit/staged-loop
    # gtests (expected: 10/10 PASS, 0 reports)
    cd <wt-tsan>/src/unit && export LD_LIBRARY_PATH=$T
    for i in $(seq 1 10); do TSAN_OPTIONS="halt_on_error=0 log_path=<out>/dt$i" DIFFTEST_SEEDS=300 DIFFTEST_FIRST=$((i*300+1)) \
        ./valkey-unit-gtests --gtest_filter='FastpathDifftest.*' --gtest_shuffle; done

Mutation (expected: 3 TSan reports, fastpath.c fpLaneExecute `L->executed++` vs fastpathMutationPeekLanes):

    cd <wt-tsan> && python3 ${R}/mutations/mut-3a.py && make -j8 SANITIZER=thread MALLOC=libc STAGED_CHECKS=yes
    sh ${R}/tsan/run-tsan-tcl.sh <wt-tsan> <outdir3> --single unit/staged-loop-lanes
    git checkout src/fastpath.c src/staged_loop.c

## 7. Release cost

    git -C <clone> worktree add --detach <wt-c> ceaa1101d && make -C <wt-c> -j8
    git -C <clone> worktree add --detach <wt-h> origin/northstar/proof-checks && make -C <wt-h> -j8
    size <wt-c>/src/valkey-server <wt-h>/src/valkey-server
    nm <wt-h>/src/valkey-server | grep -c 'fastpathWindowOpen\|kvstoreOwnTable\|kvstoreCheckOwned\|fpCheckEntryUnobserved'   # expected 0
    # per-symbol comparison: nm --size-sort -S on both, diff (logs/release-cost.txt has the result)

## 8. Checks

    LC_ALL=C grep -nP '[^\x20-\x7E\t]' ${R}/*.md ${R}/logs/* ${R}/mutations/* ${R}/tsan/*.txt ${R}/tsan/*.supp   # expected: no output
