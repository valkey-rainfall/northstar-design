# STREAM path: does any correctness test run the order S?

Date: 2026-11-11 (UTC). Revision: valkey-rainfall/valkey `northstar/proof-checks` = 71455f1c1, one commit
on 8a1e6c1b4 (patches/0009), which is on C = ceaa1101d. Build: `make -j8 STAGED_CHECKS=yes`, unit binary
as in REPRODUCE.md step 2. Host: the x86_64 dev host only. No the test hosts host and no the runner were used.

Background: PROOF.md section 1 and lemma L8. When stagedStreamEligible holds (AOF off, main spins and
takes a lane, no BCAST tracking prefix, at least one IO thread has a batch, and no segment reaches
io-threads-parallel-writes-min), main runs fastpathStagedExecuteStreaming: one client run at a time
(fpStreamExecRun), round-robin over the IO threads, and STREAM workers deliver each run's replies once
main publishes it. The order is S, not T.

## 1. The counter

INFO fastpath already had `staged_stream_phases` (STREAM phases opened). Commit 71455f1c1 adds, in
STAGED_CHECKS builds only (release builds unchanged; all new code is inside `#ifdef STAGED_CHECKS`):

| INFO field | Meaning |
|---|---|
| staged_check_stream_execs | write steps that ran the STREAM executor |
| staged_check_stream_multi | of those, steps with runs from 2 or more IO threads (S can differ from T) |
| staged_check_stream_runs | client runs main executed there |
| staged_check_stream_entries | entries main executed there |
| staged_check_stream_cuts | runs the window cut (the client continues in a later round) |

finishShutdown logs the same five numbers ("STAGED_CHECKS stream coverage: ..."), so Tcl suites run
with `--dont-clean` keep them in tests/tmp/server.*/stdout. tests/linearize/harness/driver.py now records the
six fields in each history's .meta (0 on builds without them).

## 2. Coverage of the existing tools (before)

| Tool | Settings (its own) | STREAM entries | multi | cuts | Source |
|---|---|---|---|---|---|
| difftest, FastpathLanesTest, FastpathStaged*, ReplApplyTest (gtest) | in process | 0 | 0 | 0 | by code: every test's iteration calls fastpathStagedExecute; no unit test called fastpathStagedExecuteStreaming |
| unit/staged-loop-lanes (35 tests) | io-threads 5, min 1 in most servers | 423 | 0 | 0 | logs/stream-s/coverage-tcl-g7.txt |
| unit/maint-lanes | | 2 | 0 | 0 | same |
| integration/replica-parallel-apply | | 10,311 (primaries) | 0 | 0 | same |
| unit/staged-loop-stream (9 tests; a STREAM suite, not in the lane set) | | 35,485 | 50 | 317 | same |
| linearize, 4 x 10 s, 8 clients, pipeline 0/4 (Phase 6 settings: io-threads 5, min 1, cores 4-7) | | 1,409 of 654,554 ops | 193 | 0 | logs/stream-s/lin-before-lanes.summary.txt |
| g7 black-box (blocking, WATCH, notify, AOF, expiry) | lanes server, min 1 | 81 | 0 | 0 | coverage-tcl-g7.txt |

So: the gtests never ran S. The lane Tcl suites and g7 ran it only with one IO thread at a time
(multi 0), where S equals T. Only the linearize histories (193 steps) and staged-loop-stream (50 steps)
ever interleaved two threads' runs, and no test ever ran a cut run under an oracle except
staged-loop-stream. With min 1, STREAM opens only in steps with no lane entry (barrier-only steps).

g7 note: phase8/g7/run_all.sh passed the script's own arguments before the port, so every driver
stopped at argument parsing ("invalid literal for int()"). Fixed in this commit (one line); with the fix
all 10 g7 checks pass (5 lanes, 5 baseline, failures 0).

## 3. Forced STREAM (after)

Linearize harness, server.sh lanes mode plus the extra arguments below; server on cores 2-7 (main
spins: `staged_main_shares_cpu:0`, `staged_main_lane:1`, 4 IO workers, checked with INFO during F1),
driver and checker on cores 8-13; checker per history limited to 300 s (`CHECK_TIMEOUT`). Script:
tests/linearize/harness/run_stream.sh (new). Every history checks per-key linearizability, the MSET/MGET
snapshot group and the account sum, as in tests/linearize.

| Matrix | Extra server args | Clients, pipelines | Seeds | Histories | Verdict | STREAM entries | multi | cuts |
|---|---|---|---|---|---|---|---|---|
| F1 | --io-threads-parallel-writes-min 1000000 --staged-main-lane yes | 16; 0, 4, 8 | 101-106 | 6 | 6 PASS | 171,161 | 3,222 | 3,891 |
| F2 | --io-threads-parallel-writes-min 32 (the default) --staged-main-lane yes | 8; 0, 2, 3 (at most 24 pending < 32) | 201-206 | 6 | 6 PASS | 149,301 | 5,715 | 844 |
| F3 | as F1 plus --prefetch-batch-max-size 2 (window 2: many cuts) | 32; 0, 2 | 301-304 | 4 | 4 PASS | 69,110 | 2,156 | 9,886 |
| total | | | 16 seeds | 16 | 16 PASS, 0 FAIL | 389,572 | 11,093 | 14,621 |

16 histories, 2,500,798 recorded ops, 155,630 STREAM phases. In F2, 2 histories also ran 564 lane
entries (16 lane phases): with pipeline 3 some steps reached 32 pending entries.

A first F1 attempt with pipeline 16 (logs/stream-s/lin-f1-attempt1.summary.txt): 2 histories PASS; the
checker did not finish the pipeline-16 history within the outer time limit (search too wide), so no
verdict. Pipeline 16 was dropped; the checker limit was added to run_stream.sh.

Differential test: new FastpathDifftest.StreamExecutorMatchesPlainOverRandomPrograms. Each random
program runs with the STREAM executor (window 16, and window 2) and must give the plain executor's
reply bytes for every client and the same final dataset. The test has one IO thread, so S equals T and
the plain executor is a valid oracle; it checks program order and cut-run resumption, not the
interleaving across threads (that is the linearize harness's job).

| Run | Seeds | STREAM entries | cut runs | Result |
|---|---|---|---|---|
| DIFFTEST_SEEDS=2000 | 1-2000 | 273,572 | 56,153 | PASS (all 3 difftest tests) |
| DIFFTEST_SEEDS=20000 | 1-20000 | 2,719,064 | 558,036 | PASS |

`--gtest_filter='Fastpath*:ReplApply*' --gtest_shuffle`: 28 tests PASS.

## 4. Mutations

Applied on a local scratch branch (not pushed) and reverted there; the revert
commit's tree equals 71455f1c1 (`git diff 71455f1c1` empty). Scripts and diffs in mutations/.

S-a, mutations/mut-sa.py: fpStreamExecRun executes the first two entries of every run of 2 or more
entries in swapped order (replies stay with their entries).

| Tool | Result |
|---|---|
| STREAM difftest, 2000 seeds | caught: 1,306 of 2,000 seeds differ (first: seed 1) |
| linearize, F1 settings, seeds 101-104 | caught: 2 of 2 pipelined histories FAIL (no linearization on keys n0, n1, r0, r1, r2 ...); the 2 unpipelined histories PASS, as expected (runs of 1 entry cannot be swapped) |
| unit/staged-loop-stream | caught: 5 of 9 tests [err] (P16 per-key INCR sequence, readers behind writers, CONFIG SET under load, CLIENT KILL, obuf limit) |
| unit/staged-loop-lanes | not caught: 35/35 ok (STREAM entries there come one client at a time) |

S-b, mutations/mut-sb.py: main publishes a run (release store of `executed` up to the run's end) before
it executes it.

| Tool | Result |
|---|---|
| linearize, F1 settings | caught: the server crashed 0.16 s after start, SIGSEGV at address 0 in fpExecute on main (the STREAM worker delivered the run and freed its entries, fpFreeEntries, while main still had to execute them); 4 of 4 histories driver-error |
| unit/staged-loop-stream | caught: server crashed by signal 11, test client EOF |
| STREAM difftest | not caught, as expected: the unit test runs no STREAM worker, REPLY delivers after the write step |

S-b shows up as a crash, not as a wrong reply: in this code, an early publish frees entries main has not
run yet. A subtler early publish (reply bytes seen before they are written, entries kept) was not built.

## 5. Commands

    # build: REPRODUCE.md step 2 on northstar/proof-checks = 71455f1c1
    # Tcl coverage
    ./runtest --single unit/staged-loop-lanes --single unit/maint-lanes --single integration/replica-parallel-apply --clients 1 --dont-clean
    ./runtest --single unit/staged-loop-stream --clients 1 --dont-clean
    grep -h 'STAGED_CHECKS stream coverage' tests/tmp/server.*/stdout
    # linearize (A = this repository; VK_SRC = <wt>/src)
    export VK_SRC=<wt>/src RUNDIR=$WORK/run-lin CORES=4-7
    CLIENTS=8 PIPES="0 4" taskset -c 8-13 $A/tests/linearize/harness/run_stream.sh lanes 38610 4 10 before-lanes
    export CORES=2-7 CHECK_TIMEOUT=300
    CLIENTS=16 PIPES="0 4 8" SEED0=100 taskset -c 8-13 $A/tests/linearize/harness/run_stream.sh lanes 38621 6 10 f1-min1e6 \
        --io-threads-parallel-writes-min 1000000 --staged-main-lane yes
    CLIENTS=8 PIPES="0 2 3" SEED0=200 taskset -c 8-13 $A/tests/linearize/harness/run_stream.sh lanes 38622 6 10 f2-min32 \
        --io-threads-parallel-writes-min 32 --staged-main-lane yes
    CLIENTS=32 PIPES="0 2" SEED0=300 taskset -c 8-13 $A/tests/linearize/harness/run_stream.sh lanes 38623 4 10 f3-c32-pf2 \
        --io-threads-parallel-writes-min 1000000 --staged-main-lane yes --prefetch-batch-max-size 2
    # difftest
    DIFFTEST_SEEDS=2000 ./src/unit/valkey-unit-gtests --gtest_filter='FastpathDifftest.*'
    DIFFTEST_SEEDS=20000 ./src/unit/valkey-unit-gtests --gtest_filter='FastpathDifftest.Stream*'
    # g7
    CORES=14,15 VK_SRC=<wt>/src <the g7 Tcl coverage runner, not published>
    # mutations (then rebuild server and unit binary, rerun the tool; git checkout src/fastpath.c to revert)
    python3 mutations/mut-sa.py
    python3 mutations/mut-sb.py

## 6. Limits

- The difftest STREAM mode has one IO thread, so it cannot check an interleaving across threads; only
  the linearize histories (11,093 multi-thread STREAM steps) and staged-loop-stream do.
- The Python driver keeps few clients ready per iteration, so most STREAM steps hold runs of one or two
  threads. F3 (32 clients, window 2) has the most cuts; no matrix forced 4 threads per step.
- A linearizability check cannot see a reordering of two concurrent commands of different clients;
  that is legal by definition (SECTION.md LIN-LIMIT). S-a breaks one client's program order, which it
  can see.
- No TSan run on the STREAM path in this work (the TSan runs of STATUS.md item 3 used the lane suites,
  which opened STREAM with one thread only). The release build was not rebuilt to re-check the
  symbol list; the new code is all inside #ifdef STAGED_CHECKS.
