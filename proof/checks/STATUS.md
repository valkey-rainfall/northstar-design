# Proof checks: the assumed items of the North Star proof, checked on C

Date: 2026-11-09. Revision C = ceaa1101d (the frozen proof-of-concept commit, also in
valkey-rainfall/valkey). Branch: valkey-rainfall/valkey `northstar/proof-checks`, head 8a1e6c1b4, eight
commits on C (logs/branch-commits.txt, patches/). Host: the x86_64 dev host, gcc 11.5, googletest 1.15
from $HOME/.local, libtsan.so.0 from $HOME/.local/lib/sanitizer-rt. Nothing ran on the measurement hosts.

Status words: TESTED (a test or sanitizer ran on C and a named mutation makes it fail), ARGUED (a
written argument, no run), GUARD-ONLY (the check exists but no mutation was shown to fire it).

## The build switch

`make STAGED_CHECKS=yes` adds -DSTAGED_CHECKS, which turns `stagedCheck(x)` (server.h) into a
serverAssert and compiles in the window flag and the kvstore table-ownership check. In every other
build the macro expands to `((void)0)` and the helpers are not compiled: the release head has no
check symbol and every function the checks touch has the same size as at C (logs/release-cost.txt).
The setting persists in .make-settings like the others; `make distclean` drops it. The unit Makefile
passes the same define to the C++ tests.

## Results

| # | Item | Check | Hook | Mutation (fires?) | C passes? | Status |
|---|---|---|---|---|---|---|
| 4 | Allowlist declares all keys (O1) | gtest FastpathListsTest.LaneAllowlistDeclaresAllKeys: each of the 124 names is a top-level native command, has key specs, no spec is KSPEC_BS_UNKNOWN / KSPEC_FK_UNKNOWN / CMD_KEY_INCOMPLETE, not CMD_TOUCHES_ARBITRARY_KEYS, accepted by the gate | src/unit/test_fastpath_lists.cpp, accessors in fastpath.c | 4a `sort` added: 5 failures (specs 1, 2 unknown; count 125). YES | yes | TESTED (static); the dynamic side is item 2 |
| 5 | Deny list complete (O15, command side) | gtest ...CommandGateRefusesStateChangingCommands: accepted set == golden list of 209 commands; none blocking/admin/pubsub/transaction/scripting/connection; 60 named session-changing commands refused | same file | 5a CMD_BLOCKING dropped from the mask: 31 failures (BLPOP and friends accepted). YES | yes | TESTED (static golden list = review trigger) |
| 1 | The empty window (4.7) | `fastpathWindowOpen()` from the observer-set sampling before READ to the end of batch execution; stagedCheck in processCommand (only executors or a client a barrier entry woke), clusterProcessPacket, watchForKey, blockForKeys (only a woken client re-blocking); on the lane, fpLaneExecute re-checks that no declared key is watched or blocked on | fastpath.c, server.c:processCommand, cluster_legacy.c, multi.c, blocked.c | 1a main-path clients and bus served before the batches: processCommand fires on the first main-path command. 1b classification ignores observers: the lane re-check fires (fastpath.c:2378) in the blocked-client test. YES, YES | yes: unit/staged-loop-lanes 35/35 (cluster and replica sections included) | TESTED (window), ARGUED (the woken client's position, below) |
| 2 | Per-partition tables are a memory partition (O5) | kvstoreGetHashtable / kvstoreGetHashtableRef assert, while the kvstore is in concurrent mode, that the thread claimed the table: didx % nlanes == lane (write lane, replica plan and apply lanes) or didx == unit (MAINT) | kvstore.c, fastpath.c:fastpathStagedWriteLane, repl_apply.c (rpRunLane, replApplyRunLane), maint.c:maintRunUnit | 2a other keys' partitions not compared (the audit's m2): fires at the first multi-key lane test; the difftest aborts at the first violating seed (was 1,608 reply differences). 2b lane off by one: fires at the first lane entry. YES, YES | yes: lanes + maint-lanes + replica-parallel-apply 55/55; difftest 2,000 seeds; FastpathLanesTest x5 shuffled; ReplApplyTest 300 seeds; kvstore, barrier, lists suites; 83 tests x3 shuffled in one process | TESTED |
| 3 | Every shared plain variable crosses the barrier (L6, O7) | TSan build (SANITIZER=thread MALLOC=libc STAGED_CHECKS=yes). The barrier is C11 release/acquire plus pthread mutex/condvar, so TSan models its happens-before; no annotation needed | tsan/ | 3a main reads fp_lanes[l].executed after phaseBarrierOpen, before WaitAllDone: 3 reports, write side fpLaneExecute on an IO thread; the same read after the barrier (fpMergeLanes) is never reported. YES | 0 reports on lanes + maint-lanes + replica-parallel-apply (55/55) with no suppressions; 0 on the difftest 10 x 300 seeds, lanes x3, repl apply (100 seeds). Extra suites (fastget, speculation, staged-loop, stress): 22 reports in 7 classes, none in a lane phase, all documented in tsan/tsan.supp | TESTED for the lane paths these suites run; LANE-WRITES.md static list ARGUED |

## STREAM order S (2026-11-11, STREAM-S.md)

Branch head now 71455f1c1 (ninth commit, patches/0009): STAGED_CHECKS counters staged_check_stream_*
and a STREAM difftest. Before: the gtests ran 0 STREAM entries; the lane Tcl suites and g7 ran STREAM
only one thread at a time (0 multi-thread steps); Phase 6 linearize settings ran 1,409 entries in 4
histories. After: 16 forced-STREAM linearize histories (seeds 101-106, 201-206, 301-304; 2.50 M ops;
389,572 STREAM entries; 11,093 multi-thread steps; 14,621 cut runs) all PASS; STREAM difftest 20,000
seeds PASS. Mutation S-a (swap two entries of a run): difftest 1,306/2,000 seeds, linearize 2/2
pipelined histories, staged-loop-stream 5/9 tests. Mutation S-b (publish before the run ran): server
crash in fpExecute under linearize and staged-loop-stream. Status: TESTED (one-thread S by difftest,
multi-thread S by linearize). Also fixed: phase8/g7/run_all.sh passed arguments in the wrong order.

## Findings

- F1 (item 1, design 4.7 wording). The window is not empty of client commands in the strict sense. A
  barrier entry that readies a blocked key makes main re-execute the woken client's blocking command
  inside the window (handleClientsBlockedOnKeys at the end of processCommand, flag
  reexecuting_command), as the stock server does right after the readying command; a woken client
  may block again on the same keys (blockForKeys). The first version of the check fired on C in the
  test "lanes keep running while a client is blocked". Argument: the woken command runs at the
  barrier entry's position in T, on main, with no phase open, and re-blocks only on keys that were
  observed when the iteration was classified, so no lane entry targets them; the lane-time re-check
  covers whatever else it could change. The check allows exactly this case.
- F2 (item 3, TSan). The object header word race of design section 9 shows up as expected: the fast
  GET's LFU/LRU touch CASes the 32-bit header word while another thread (main or another IO thread
  answering SISMEMBER) reads the type bits plainly (objectGetType). READ phase only. 9 reports in the
  extra suites, 0 in the lane suites.
- F3 (item 3, TSan, new). CONFIG SET of a numeric config races with the forkless save thread reading
  it (config.c:2189 setNumericType vs rdb.c:1365 rdbSaveKeyValuePair, class K2 in tsan.supp). Not a
  lane or barrier matter; stock forkless-save code of the proof of concept. Unclassified beyond "plain int
  read on another thread"; listed, not analysed.
- F4 (item 5). The gate accepts FLUSHALL, FLUSHDB, SWAPDB, SORT, KEYS, MIGRATE, DUMP, RESTORE,
  XGROUP and XINFO subcommands as barrier entries on main (they are not lane commands). Consistent
  with design 4.4; now pinned in the golden list.
- F5 (build). `SERVER_CFLAGS += -D...` in src/Makefile duplicates on every build because SERVER_CFLAGS
  is re-read from .make-settings; DEBUG_FORCE_DEFRAG has the same shape. STAGED_CHECKS adds its define
  once (findstring guard).

## Not done / limits

- Item 3's static list (LANE-WRITES.md) is a grep, not a call-graph analysis; TSan covers only the
  paths the suites run. The lane Tcl suite uses keyspace-shard-bits 10 and io-threads 5; the task
  named 8 bits and io-threads >= 3 (8 bits is the production default; the tests' settings are the
  suite's own).
- The window check (item 1) covers the primary. The replica's run-time re-check (rpObservedInRange)
  was not touched.
- The partition check hooks every kvstore table access; a hashtable pointer held across calls is not
  re-checked (none found in lane code).
- MAINT claims one table per unit; the proof does not cover MAINT, the claim only keeps the check
  from firing there.
- The whole Tcl suite and the whole unit binary were not run with STAGED_CHECKS; the suites run are
  listed above.
