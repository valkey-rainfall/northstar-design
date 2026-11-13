# MODEL-RESULTS.md: what the executable models checked and found

Two independent executable models of the lane plan, both derived from the abstract machine in PROOF.md
section 1 and from `src/fastpath.c` at HEAD 1fb18b7d25e043f1a94794eeb9957d75a7becf9f.

## 1. Python exhaustive-interleaving checker: `model/lanes_model.py`

Standard library only. For each scenario it enumerates the executions the design permits and checks
each one against a serial reference machine.

What is modelled (following the code):
- two iterations; per iteration each client's new commands arrive as a prefix (chosen per seed), are
  parsed by the client's thread in a per-seed harvest order, and classified: lane entry (all keys on one
  lane), split MSET/MGET (one part per lane, parts carry the whole's segment), or barrier (cross-lane
  non-splittable command, WATCH/EXEC, any key observed by a WATCH at classification time);
- fast GET: a leading run of GETs of a client with nothing in flight is answered in the READ phase from
  the state at the start of the iteration (fpSpeculate gate);
- the write step as fpExecuteWithLanes: thread-major T order, pending segment parts run as one lane
  phase before each barrier, barrier alone on main; the issue-29 rule (a barrier that adds a WATCH makes
  the rest of the iteration serial);
- a lane phase explores ALL interleavings of the per-key steps of all lanes (each lane keeps its T
  order); SET/MSET write, GET/MGET read, INCR read-modify-write, DEL per key, RENAME as read, write,
  delete steps; a split MGET's reply is assembled from its parts in key order;
- replies delivered per client in batch order in REPLY; WATCH dirty flags are set only by main-thread
  writes (lanes do not touch watched_keys, as in the C code);
- the checker builds the design's claimed linearization S (fast GETs of the iteration, then T) and
  asserts (G2) S lists each client's commands in program order, (G1/G4/G5/G6) the replies the design
  delivered equal the replies of S on the reference machine, (G3) the final state equals S's. G6 holds
  because S puts an iteration after everything acknowledged in earlier iterations (PROOF.md L8).

Scenarios: 5 hand-made (MSET vs split MGET from another thread plus later fast GETs; a pipeline across
lanes with a cross-lane RENAME barrier from another client; WATCH/EXEC against lane writes in two
shapes; acknowledged write then read with INCR counting) plus N random scenarios (3 keys over 3 shards,
2 lanes, 3 clients on 2 threads, programs of 1-3 commands from SET/GET/MSET/MGET/INCR/DEL/RENAME/
WATCH+EXEC, random arrival split over 2 iterations and random harvest order).

Results (30 random seeds, `MODEL-RUN.log`; 80 seeds in `MODEL-RUN-seeds80.log`):

| Variant | What is broken | Executions explored | Violating | Scenarios hit | Result |
|---|---|---|---|---|---|
| correct | nothing | 1090 | 0 | 0 | PASS |
| V1 reverse_lane_order | one lane runs its entries in reverse T order | 1090 | 563 | 15 of 35 | caught: MGET a b returns ('2', None) while serial gives ('2','2') |
| V2 no_barrier_for_cross_lane | a cross-lane non-splittable command runs on the lane of its first key | 1397 | 536 | 14 | caught: split MGET sees ('1','2'), a torn MSET |
| V3 fast_get_ignores_inflight | fast GET answered while the client's earlier commands wait in the batch | 947 | 167 | 8 | caught as a G1/G2 violation: reply of GET c precedes RENAME a c of the same client |
| V4 stale_barrier_read | missing happens-before: a barrier may read the state before the last lane phase | 1576 | 67 | 8 | caught: RENAME on main answers ERR where serial says OK (lost lane write) |
| V5 split_parts_cross_segments | a split entry's later parts run one segment later | 223 | 59 | 14 | caught: MGET a b returns ('2', None) |
| V6 no_issue29_recheck | a barrier that adds a WATCH does not make the rest of the iteration serial (the S1 state) | 1120 | 2 | 1 | caught: EXEC succeeds where serial aborts (watch-same-iteration scenario) |

Every lane phase in these scenarios was explored exhaustively (the per-phase cap of 400 interleavings
was not reached: the largest phase had 3 lanes with at most 7 steps each). The random generator rarely
produces the issue-29 shape; the hand-made scenario `watch-same-iteration` is what catches V6.

Caveats of the Python model: a per-key step is atomic; the model does not include the serial-segment
fallback below io-threads-parallel-writes-min (it always runs a lane phase, which is the harder case),
fast GET on a replica, cluster slot lanes, the STREAM phase, requeue, or client lifecycle.

## 2. TLA+ / TLC: `tla/Lanes.tla`

TLC 1.7.4 (tla2tools.jar downloaded from the TLA+ GitHub release page into scratch; Corretto 21 on the
host) with `-workers 2` on cores 12,13. The spec models one iteration: a fixed T (harvest order) of
command records, classification into lane / split / barrier, segments cut by barriers, each lane's
per-key steps as separate actions interleaved by TLC, barriers as atomic actions between phases, and the
invariant `SerialEquivalent`: when every phase has run, the state and every reply (barrier replies
included, split MGETs assembled by key position) equal the serial execution of T. Four broken variants
are CONSTANT flags: ReverseLane (V1), NoBarrierCross (V2), StaleBarrier (V4: the barrier may read the
pre-phase state and its writes land on top of the real one), SplitCrossSeg (V5). The issue-29 variant
and fast GET are not in the TLA+ spec (they need WATCH state and iterations; the Python model has them).

Instances: MC1 (4 keys over 4 shards, 2 lanes, 12 entries from 6 clients on 2 threads: two MSETs vs
MGETs from another client, a cross-lane DEL barrier, a same-lane RENAME, INCRs, a 3-way split MGET);
MC2 (5 keys, 3 lanes, 14 entries from 5 clients, two barriers: cross-lane RENAME and cross-lane DEL,
3-key MSET vs MGETs, three INCRs on one key from three clients).

| Config | Result | States generated / distinct |
|---|---|---|
| MC1 correct | No error | 137 / 80 |
| MC1 V1_reverse | Invariant SerialEquivalent violated | 137 / 80 |
| MC1 V2_nobarrier | violated | 806 / 456 |
| MC1 V5_splitseg | violated | 122 / 73 |
| MC1 V4_stale | violated | 242 / 140 |
| MC2 correct | No error | 285 / 133 |
| MC2 V1_reverse | violated | 285 / 133 |
| MC2 V2_nobarrier | violated | 8663 / 3596 |
| MC2 V5_splitseg | violated | 220 / 108 |
| MC2 V4_stale | violated | 475 / 221 |

Why the state counts are small: with the correct partition, the state after any prefix of a lane phase is
determined by the per-lane step counters alone (the lanes touch disjoint keys), so TLC's distinct states
are the grid of counters. That smallness is itself L1 made visible: V2 (a cross-lane entry on one lane)
multiplies the distinct states by 27 in MC2 because the lanes now interfere. Logs: `tla/tlc-*.log`
(each holds TLC's full output including the counterexample trace for the violated configs).

## 3. What the two models agree on and where they differ

Both say: the correct plan is serially equivalent on every explored schedule, and each of the four
required broken variants (lane order reversed; cross-lane command not a barrier; speculative read without
the gate / stale read without happens-before; split parts across segments) produces a counterexample.
The Python model adds the fast GET gate (V3) and the issue-29 recheck (V6) and multi-iteration real-time
order; the TLA+ spec is the cleaner statement of L1-L5 for one iteration and is exhaustive by
construction. Neither model touches the C code.
