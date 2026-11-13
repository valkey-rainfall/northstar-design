# Phase 23b: the lane differential test at F (commit 6ba80d232)

STATUS: DONE (2026-11-06). No server code was changed.

## Branch

| | |
|---|---|
| Commit | valkey-rainfall/valkey 6ba80d232 |
| Base | 8cbc8236017d4e6e16264cffb37e664a4c1854df (PRFIX = F f01d005ea plus our 29 fix and test commits) |
| Head | 6ba80d232 "test: port the lane differential test and the split-command lane tests" (one commit; author and committer Rain Valentine <rsg000@gmail.com>, Signed-off-by; ASCII only) |
| Files | src/unit/test_fastpath_difftest.cpp (new, 580 lines), src/unit/test_fastpath_lanes.cpp (new, 534 lines). Patch: 0001-test-port-difftest.patch |
| Build | gcc 11.5, gtest 1.15 in ~/.local (make commands as in build-asan.sh) |

## What was ported, and how it was adapted to F

Source: tests/difftest/test_fastpath_difftest.cpp (Phase 6, HEAD 1fb18b7d) and
src/unit/test_fastpath_lanes.cpp at FIX (91dbb9c3). Only test code; the server is PRFIX's.

- FastpathDifftest (2 tests): the seeded differential test. Changes against the Phase 6 file:
  - A FOURTH executor, MODE_LANES_PREFETCH: the lanes with `io-threads-lane-prefetch` on
    (`prefetch-batch-max-size` 16), which is F's new lane walk (collect the lane's entries of the phase in
    T order, prefetch their keys in batches, run them in the collected order; 67805ac58, f7e287c5e). Its
    replies and dump must equal the other three; the engagement check requires
    `fastpath_write_lane_prefetches` > 0 for it (and 0 for the plain lane run).
  - Keys chosen at suite start from the build's table hash (690f85bd8 changed the hash of short keys):
    three per lane, six distinct shards, the first "k<n>" names that fit. At F: lane 0 = k1 (shard 6), k2
    (4), k3 (14); lane 1 = k0 (13), k4 (3), k6 (11). The replay output (DIFFTEST_SEED) prints them.
  - The shared test_server_init.hpp helpers, `blocking_keys_unblock_on_nokey`, and the tear-down that
    clears the IO thread ready slot and deletes the event loop, so the suite runs in one process with the
    other suites (on F the gtest binary hung when two fast-path suites shared a process before our
    test_server_init.hpp commit on PRFIX).
  - Everything else (generator, 40 command shapes, three rounds, write-order permutation, byte-for-byte
    comparison of reply streams and the dataset dump, SerialExecutorIsDeterministic) is unchanged, so a
    seed builds the same program shape as in Phase 6 with the new key names.
- FastpathLanesTest (6 of the 11 tests at FIX): SplitMsetAndMgetKeepPipelineOrderAcrossLanes,
  SplitMgetAssemblesKeyOrderWithNilsAndSpilledValue, ReaderNeverSeesHalfOfASplitMset,
  SerialFallbackMatchesLanes, MultiKeyLaneCommandsAcrossTwoShardsRunAsBarriersAndMatchOneShard (18
  command kinds), PipelineAclRevokeThenSetRefusesTheSet. Keys picked at suite start (two on lane 0, three
  on lane 1, distinct shards) and substituted for the literals.
- NOT ported, because they test the audit stack's generation guards, which F does not have:
  LaneEntryTaggedBeforeMainRevokesIsRefused (ACL epoch), KeyObserverShardRecordLimitsTheRecheckToAffectedShards
  and KeyObserverShardRecordUsesTheParserSlotInClusterMode (the observer record), and the two window
  oracle tests BlockingPopInTheWindowIsServedBeforeTheNextLaneEntry and
  WatchInTheWindowAbortsTheExecAfterTheLaneWrite (they force a main-path WATCH or BLPOP into the window
  between the read phase and the lanes, which F's loop keeps empty and does not guard). The cluster seam
  suite FastpathClusterLanesTest (slot-ownership guard) was not ported either.

## Results at 6ba80d232 (x86, gcc 11.5, 16 cores; logs/)

| Run | Result | Log |
|---|---|---|
| FastpathDifftest, seeds 1..2000, four executors | PASS, 2.1 s | run-seeds-1-2000.log |
| 20 repeats, fresh process each, seeds 2001..42000 (2000 per run), --gtest_shuffle | 20 of 20 PASS | run-repeats-summary.txt |
| FastpathLanesTest, --gtest_shuffle --gtest_repeat=20 | 6 tests x 20, 0 failures | lanes-shuffle-x20.log |
| 14 suites in one process (the Phase 22 set of 12 plus the two new ones), --gtest_shuffle --gtest_repeat=20, DIFFTEST_SEEDS=200 RADIFF_SEEDS=300 | 147 tests x 20 iterations, 0 failures, 5.6-5.9 s per iteration | multi-shuffle-x20.summary.txt |
| Mutations (mutate_f.py; src/fastpath.c of PRFIX changed, rebuilt, 2000 seeds, DIFFTEST_MAXFAIL unlimited; then restored and rebuilt) | m1 detected 1662 of 2000; m2 1608; m3 1346; m4 1308 (the same counts as at HEAD in Phase 6) | mut-m1..m4.log (first 300 KB), mut-m*-full.log.gz |
| ASAN build (make SANITIZER=address, detect_leaks=0 because of the pre-existing fixture leaks): difftest 2000 seeds; FastpathLanesTest x20; the 14 suites x3 | see "ASAN" below | asan-*.log |

So 42,000 distinct seeds, each run through four executors (lanes, lanes with key prefetch, serial
segments, plain), with no difference in any reply byte or in the final dataset, and every one of the
four production mutations caught from the first seed. The m1 mutation at F reverses the lane's collected
run list (the Phase 6 anchor, the per-entry walk, no longer exists); m2-m4 use the Phase 6 anchors,
which are unchanged at F.

### ASAN

Build: `make SANITIZER=address` of 6ba80d232 in a detached scratch worktree (build-asan.sh; libasan.so.6
from ~/.local/lib/sanitizer-rt; `ASAN_OPTIONS=detect_leaks=0`, as in Phases 21 and 22, because of the
pre-existing suite-setup leaks of the fixtures). Three runs, 0 AddressSanitizer reports in all of them
(logs/asan-driver.log is the driver's summary):

| Run | Result | Log |
|---|---|---|
| FastpathDifftest, seeds 1..2000, four executors | PASS, 0 reports | asan-difftest-2000.log |
| FastpathLanesTest, --gtest_shuffle --gtest_repeat=20 | 20 of 20 iterations PASS, 0 reports | asan-lanes-x20.summary.txt |
| The 14 suites in one process, --gtest_shuffle --gtest_repeat=3, DIFFTEST_SEEDS=200 RADIFF_SEEDS=300 | 147 tests x 3, 0 failures, 0 reports, about 11 s per iteration | asan-multi-x3.summary.txt |

UBSAN and TSan: not run (no UBSAN runtime on this host; TSan would need a threaded harness, the difftest
runs every lane inline on one thread, so TSan has nothing to see in it).

## Window probe (informational, NOT committed; logs/window-probe.log)

The two FIX oracle tests that force a main-path command into the window were appended to the lanes test
file in the worktree, built, run once, and the file restored to the committed version. Result at F: both
FAIL, as expected from the code reading in SECTION.md (the window is unguarded at F):

- BlockingPopInTheWindowIsServedBeforeTheNextLaneEntry: the lane runs the RPUSH, so the same pipeline's
  LLEN replies 1 where a serial server replies 0 (the blocked client would have been served first); the
  blocked client stays blocked in the iteration; the list is not popped; no serial segment.
- WatchInTheWindowAbortsTheExecAfterTheLaneWrite: the EXEC did abort (in this inline harness the lane's
  touchWatchedKey runs on the calling thread; in production that is the cross-thread write to watch state
  that an open tracking item describes for plan lanes), but the iteration did not go serial.

This is not a defect of F in its own loop (nothing opens the window on a primary; SECTION.md section 2
item 3 and rule 7) and it is not a finding against PRFIX. It is the evidence that rule 7 is the only
protection at F, recorded for the GUARDS row of SECTION.md 5.3.

## Preserved versus discarded

Preserved: this folder (STATUS.md, REPRODUCE.md, README.md, the patch, mutate_f.py, the three run
scripts, logs/). Discarded: the ASAN worktree and the scratch build logs.
