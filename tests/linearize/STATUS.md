# W-C2 linearize: STATUS

STATUS: complete (2026-10-29 04:48 to 05:20 UTC)

Revision under test: HEAD = origin/audit/issue29-counter-recheck = 1fb18b7d25e043f1a94794eeb9957d75a7becf9f
(results/sha.txt has the remote, the S1 SHA and the toolchain). Build: `make -j4` under `taskset -c 4-7` in a
detached worktree. Servers bound to 127.0.0.1 only, ports 38500-38999, cores 4-7, `--save "" --appendonly no`.
Configs: lanes = `--io-threads 5 --io-threads-parallel-writes-min 1` (fast path on by default, keyspace shard bits 8);
baseline = `--io-threads 1 --io-threads-fast-path no` (stock behaviour of the same binary). Driver: 8 clients, 10 s per
history, odd seeds not pipelined, even seeds pipelined 4; seed = history number.

## Summary

| Check | Guarantees | lanes (30 x 10 s) | baseline (30 x 10 s) | lanes + replica (6 x 10 s) | mutant |
|---|---|---|---|---|---|
| Per-object linearizability (WGL) | G1 G2 G3 G4 G6 | PASS 30/30, 6,852,559 projected ops | PASS 30/30, 6,381,958 | PASS 6/6, 789,929 | FAIL on both pipelined histories, PASS on the non-pipelined one |
| MGET snapshot vs MSET/MSETNX/DEL-many | G4 | PASS, 522,956 MGETs | PASS, 487,001 | PASS, 60,206 | (covered by the WGL failure) |
| Transfer sum (MULTI/EXEC and EVAL) | G5 | PASS, 341,899 account reads, 417,529 transfers | PASS, 318,494 / 389,481 | PASS, 39,336 / 48,219 | PASS (not affected by the mutation) |
| Replica GET after WAIT 1 | G8 | n/a | n/a | PASS 907/907 | n/a |
| Engagement asserted per history | | lane entries min 75,737, total 5,522,856; fp_reads 1,963,966; fp_writes 1,750,288; speculated 252,356 | all fast-path counters 0 (expected) | lane entries min 53,932; replica repl_parallel_applied 116,817, repl_apply_phases 59,009, repl_lane_barriers 418,248, repl_lane_rechecks 0, repl_lane_demoted 0 | lane entries > 0 |

Total: 66 histories on HEAD, 7,788,116 recorded operations, 0 violations. The only RESP errors in every history are
`RENAME ... ERR no such key` (expected, part of the pair spec); counted in resp_errors (63,919 lanes, 59,727 baseline).
Max front (concurrent operations the search had to consider) was 8 everywhere, so the WGL search never hit its
step budget and every PASS is a complete search, not a timeout.

Per-history tables: results/lanes/summary.txt, results/baseline/summary.txt, results/lanes-replica/summary.txt
(columns: n pipeline ops errors verdict lane_entries lane_phases barriers fp_reads fp_writes speculated). Per-history
engagement deltas and key-to-shard maps: results/*/hNN.meta; checker output: results/*/hNN.check.

## Checker self-test (results: `python3 tests/linearize/harness/selftest.py` prints "selftest: ALL OK")

| # | history | expected | got |
|---|---|---|---|
| 1 | good-sequential | PASS | PASS |
| 2 | good-concurrent-either (overlapping GET may see old or new) | PASS | PASS |
| 3 | bad-stale-read (GET after an acknowledged SET returns the old value, G6) | FAIL | FAIL |
| 4 | bad-classic-two-readers (per-client consistent, not linearizable) | FAIL | FAIL |
| 5 | good-incr | PASS | PASS |
| 6 | bad-incr-lost-update (two INCR return 1) | FAIL | FAIL |
| 7 | good-snapshot (MSET/MGET/DEL-many/MSETNX, one winner) | PASS | PASS |
| 8 | bad-snapshot-torn (MGET mixes two MSET tokens) | FAIL | FAIL |
| 9 | bad-snapshot-stale (consistent snapshot but stale in real time) | FAIL | FAIL |
| 10 | bad-msetnx-two-winners | FAIL | FAIL |
| 11 | good-rename | PASS | PASS |
| 12 | bad-rename-both-present (value visible under both keys at once) | FAIL | FAIL |
| 13 | good-transfer-sum | PASS | PASS |
| 14 | bad-transfer-sum (reader sees half a transfer) | FAIL | FAIL |
| 15 | good-pipelined | PASS | PASS |
| 16 | bad-pipelined-order (reply order would be linearizable without program order, G2) | FAIL | FAIL |

## Mutated server (results/mutant-*, patch: mutation-reverse-lane-order.patch)

Mutation: in fastpathStagedWriteLane (src/fastpath.c) each lane runs a thread's entries of one segment in reverse
order instead of T order. Build: HEAD plus the patch, same flags.

| history | pipeline | ops | verdict | note |
|---|---|---|---|---|
| mutant-pipelined-seed1 | 4 | 55,200 | FAIL | all 12 objects non-linearizable; first LIN-FAIL on key n0 (GET nil, GET "1", INCR 2 cannot be ordered); history kept gzipped |
| mutant-pipelined-seed2 | 4 | 61,320 | FAIL | all 12 objects non-linearizable |
| mutant-unpipelined-seed3 | 0 | 24,497 | PASS | expected: entries of different clients inside one segment are concurrent in real time, so reversing them is a legal linearization. The mutation is visible only through per-connection program order (G2). |

This is an honest limit of black-box history checking (the specification allows any order among concurrent
operations) and the reason the pipelined configuration is part of every matrix. The unit-level differential test
(W-C1) is the right tool for reorderings that stay inside a segment.

## Replica detail

Replica started as `lanes --replicaof 127.0.0.1 38530`, attached before the first history; the driver asserts
`WAIT 1 5000 == 1` at setup. One extra connection per history does SET k v (primary), WAIT 1 0 (primary), GET k
(replica); 907 such reads, every one returned the acknowledged value. The replica applied the stream in parallel
(repl_parallel_applied 116,817, repl_apply_phases 59,009, 0 demotions, 0 rechecks; results/lanes-replica/
replica-info-{before,after}.txt). Note the WAIT round trip limited this to about 150 reads per 10 s history.

## Not done

- Only one mutation (reverse lane order). "MSET parts across segments" was not built: a naive change makes the lane
  cursor wait for a segment that never runs, and there was no time to do it safely.
- Replica reads are only the dedicated per-connection key; the replica's view of the snapshot group and accounts
  was not checked (would need the replica history merged with the primary's under one clock, which it is: same
  host, but the checker does not yet take two files).
- No cluster slot lanes, no AOF/RDB, no expiry or eviction, no WATCH in these histories.
- Checker complexity: the WGL cache key uses a Python big-int bitmask over all ops of an object (up to ~200k);
  fine here (seconds per history) but it is not a Jepsen-scale tool.

## Preserved (outside scratch) versus discarded

Preserved in this repository:
- tests/linearize/harness/{driver.py, checker.py, selftest.py, resp.py, server.sh, run_matrix.sh}
- tests/linearize/{README.md, STATUS.md, REPRODUCE.md, mutation-reverse-lane-order.patch}
- tests/linearize/results/sha.txt (full SHAs, remote, gcc, python, cores)
- tests/linearize/results/{lanes,baseline,lanes-replica}/summary.txt, hNN.meta, hNN.check (all 66 histories),
  lanes-replica/replica-info-{before,after}.txt
- tests/linearize/results/*.jsonl.gz: one failing mutant history (seed 1, pipelined) and four passing HEAD
  histories (lanes and baseline, pipelined and not, seeds 100/104), each under 2.1 MB gzipped, re-checkable offline
  (REPRODUCE.md step 6); their .meta/.check/.drv files
- results total about 8 MB
Discarded (trivial to regenerate): the two build trees $WORK/wt-linearize and wt-linearize-mut
(binaries, objects), server data dirs and logs under $WORK/run-linearize, the 61 passing raw histories of
the matrices (12-25 MB each uncompressed; their summary lines, meta and check output are kept).
