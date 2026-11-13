# PROOF.md: why the write-lane plan keeps Valkey's ordering and atomicity guarantees

Revision: HEAD = origin/audit/issue29-counter-recheck (1fb18b7d). Line numbers are from `src/fastpath.c`,
`src/staged_loop.c`, `src/phase_barrier.c`, `src/repl_apply.c`, `src/db.c` at that revision unless a file
is named. S1 (927094894) differs only where said.

Reading guide: section 1 defines the abstract machine, section 2 proves lemmas L1-L8, section 3 is the
hard case (split MSET/MGET against readers on other clients), section 4 lists what the argument does NOT
cover. The assumptions the proof takes from the C code are numbered O1-O20 and tabulated with their status
in OBLIGATIONS.md. The executable cross-check is model/lanes_model.py (MODEL-RESULTS.md).

Verdict in one paragraph: the lane plan is a bulk-synchronous schedule. Every iteration reads all input
first, then executes, then replies. Inside the execution step, the plan is a total order T (the harvest
order, thread-major) cut into segments by barrier entries; a segment runs its entries on lanes, one lane
per group of keyspace shards, each lane in T order; a barrier runs alone on main. Because entries on
different lanes of one segment touch disjoint hashtables, every lane schedule is trace-equivalent to the
serial execution of T. A split MSET or MGET occupies one position in T and all its parts run in the same
segment, so no other command can observe it half done. Readers on other clients never read the keyspace
during a lane phase except as lane entries themselves, which are ordered by T. The proof is complete
relative to twenty obligations on the C code; all twenty are satisfied by code reading at HEAD, three of
them (O9, O12, O17) only because of fix commits after S1, and two (O7, O18) rest on an assumption about
code outside the files studied (kvstore concurrent mode and the IO-thread job set) that this worker did
not re-read.

## 1. The abstract machine

- Keys K, values V. State sigma : K -> V union {absent}. A keyspace shard function shard : K -> {0..S-1}
  (`getKVStoreIndexForKey`, db.c:268-271: the key hash masked by `keyspace_shard_bits`, an immutable
  config, config.c:3529). Lane of a key: lane(k) = shard(k) mod n where n = number of lanes this iteration
  (fp_nlanes, fastpath.c:1747-1749).
- A command c has a declared read set R(c) and write set W(c), both subsets of K, computed by
  `getKeysFromCommand` (fastpath.c:617). keys(c) = R(c) union W(c). Its semantics is a function
  [[c]] : state -> (state, reply) that reads only R(c) and writes only W(c). Commands whose key set is
  not statically declared (EVAL, SORT BY, SCAN, ...) are not lane commands (O1).
- Clients send sequences of commands. Each fast-path client is read by exactly one IO thread in one
  iteration (the fd is claimed once through the atomic cursor, fastpath.c:1682-1718) (O2).
- An iteration produces a plan: for each thread t, the harvest sequence H_t (commands in the order the
  thread parsed them, each client's commands contiguous and in program order, fastpath.c:874-955). The
  total order T is the concatenation H_0 H_1 ... H_m (thread 0 is main's own share when it takes a lane).
  T is what fpExecuteWithLanes (fastpath.c:2452-2487) walks: `for tid ... for s ...`.
- Each entry of H_t is classified (fpClassify, :780-797) into exactly one of
  - a lane entry with lane(e) = lane(k) for the single lane all its keys fall in (fpLaneOf, :647-660;
    fpKeysShard, :610-640),
  - a split entry (MSET, MGET only, standalone with shards on): one part per lane that owns at least one
    of its keys, each part holding exactly the keys of its lane (fpTrySplit, :686-778),
  - a barrier entry: anything else (not a lane command, keys in several lanes and not splittable, a key
    observed by WATCH or a blocking client, ACL not pre-approved, cluster slot not stably served).
- Barriers cut H_t into segments seg_t(0), B_t(0), seg_t(1), B_t(1), ..., seg_t(b_t): entry e gets
  seg(e) = number of barriers before it in H_t (`e->seg = t->nbarriers`, :783).
- Execution order (fpExecuteWithLanes): a running set P of "pending segment parts". For t = 0..m, for
  s = 0..b_t: add (t, s) to P; if s < b_t: run P as one lane phase (or serially, below), empty P, run
  B_t(s) alone on main. After the last thread, run the remaining P. So a lane phase runs the parts
  seg_t(b_t), seg_{t+1}(0), ..., seg_u(s) that lie between two consecutive barriers of T.
- A lane phase: main opens the WRITE phase on the barrier (stagedRunWritePhase, staged_loop.c:631-644);
  lane l (one thread) runs, for each part (t, s) of P in P's order, the entries of H_t with lane l and
  seg s in H_t order (fastpathStagedWriteLane, fastpath.c:2081-2105). A split part is a lane entry of
  its lane with the same seg as its whole (fpTrySplit :737-746, 762-766).
- A serial segment: when P has fewer than io-threads-parallel-writes-min entries, or lanes became
  disallowed, main runs P's entries itself in T order, whole (fpSerialSegment :2370-2396; a split entry
  runs whole because its parts are not batch entries, :768-770).
- Replies: each entry's reply is stored in its batch; the REPLY phase sends each client's replies in
  batch order (fpDeliverRange :1233-1262), assembling a split entry from its parts in key order
  (fpSplitAssemble :1182-1230).
- Fast GET: during the READ phase, an IO thread answers a leading run of GETs of a client immediately,
  only if the client has no command in flight (`c->fp_inflight != 0` returns, :956) and only at depth 0.

Bulk-synchronous structure of one iteration (stagedLoopIteration, staged_loop.c:511-545):
collect (main: beforeSleep) -> READ (all threads: read, parse, fast GET, classify; keyspace read-only)
-> write step (main: fpExecuteWithLanes; inside it WRITE phases on all threads) -> REPLY -> crons -> MAINT.
Only one barrier phase is open at a time; a STREAM phase (replies of main-executed entries sent while main
goes on) is closed with a full wait before a WRITE phase opens (staged_loop.c:189-190, 637). When a STREAM
phase is open, no lane phase runs in that iteration: main alone executes every entry, taking one client
run (one client's consecutive entries) from each thread in turn, round after round
(fastpathStagedExecuteStreaming; fpStreamExecRun runs exactly one run). The serial order main executes in
is then S, an interleaving of the threads' batches that keeps each client's program order, not T.
(Correction of 2026-11-06, Phase 23f and 23g: the Phase 6 text treated T as the order of every path. The
STREAM path exists since 0eba7febf, an ancestor of S1, and the code is byte-identical at S1, F and C.)

## 2. Lemmas

Notation: for a set E of entries with a total order <, serial(E, <) is the state and the replies obtained
by applying the entries of E one after another in <-order from the phase's start state. Two operations
commute when they touch disjoint key sets: [[a]] then [[b]] equals [[b]] then [[a]] in state and in both
replies, because each reads and writes only its own keys. (Mazurkiewicz: two schedules that differ only by
swapping adjacent independent operations are trace-equivalent; trace equivalence is an equivalence relation,
and trace-equivalent schedules give the same final state and the same reply for every operation.)

### L1 (partition). Two entries placed on different lanes of one lane phase have disjoint key sets, so they commute.

Proof. A lane entry e on lane l has every declared key k with shard(k) mod n = l (fpKeysShard returns -1
unless all keys are in one shard, :626-636; fpLaneOf lane = shard mod n, :659). A split part on lane l
holds exactly the keys k of its whole with lane(k) = l (fpTrySplit :704-712, 755-761). So keys(e) is a
subset of {k : lane(k) = l}. For l != l' the sets are disjoint. Reads and writes of e touch only
hashtables of its shards (O3: the executor runs cmd->proc with ec->slot = e->shard or, for split parts
and one-lane split entries, slot -1 so each key is hashed, db.c:278-282; O4: lazy expire inside a lane
deletes only the key it read, db.c:526 asserts exec_lane; O5: the per-shard tables of keys, expires and
keys_with_volatile_items are the only keyspace structures a lane writes, and kvstore is in concurrent
mode so per-table counters are reconciled afterwards, db.c:578-600). QED.

Dependence relation for a lane phase: a -> b iff keys(a) and keys(b) intersect. By L1 it relates only
same-lane entries.

### L2 (per-lane order is T order). Within one lane phase, each lane runs its entries in T order. Hence for any key k, the writes and reads of k in the phase happen in T order.

Proof. fastpathStagedWriteLane walks fp_parts in order; fp_parts is filled by fpAddPart in the order
(t, s) of the outer loop of fpExecuteWithLanes (thread-major, then segment), which is the order of T
restricted to segments. Inside a part the lane walks `th->lane_ents[lane]` from its cursor, skipping
entries of earlier segments and stopping at a later one (:2092-2101). lane_ents[lane] is appended in
harvest order (fpClassify :788-790, fpTrySplit :740-744, 762-766), which is H_t order. So lane l runs the
entries of lane l in T order. Every entry touching k is on lane(k) (L1), so all operations on k in the
phase are in T order. QED.

(O6: the cursor is reset to 0 for all lanes at the start of fpExecuteWithLanes, :2461, and advanced only
by the owning lane thread, so no entry is skipped or run twice. O7: lane_ents, seg and fp_parts are
written by IO threads in READ and by main before the WRITE phase opens, and read by lane threads after the
phase opens; L6 gives the happens-before.)

### L3 (barriers totally order segments). Let P_0, B_0, P_1, B_1, ..., P_r be the pending sets and barriers of one iteration in execution order. Every operation of P_i completes before B_i starts, B_i completes before any operation of P_{i+1} starts, and the serial order "P_0 in T order, B_0, P_1 in T order, B_1, ..." equals T.

Proof. Each P_i runs inside one stagedRunWritePhase (or serially on main); main returns from it only after
phaseBarrierWaitAllDone, that is after every lane called phaseBarrierDone (phase_barrier.c:101-116,
176-180), and only then runs fpMergeLanes and B_i (fpRunSegment :2397-2431 then fpExecuteWithLanes
:2473-2480). B_i runs on main while no phase is open, so no lane thread touches the keyspace (O8). P_{i+1}
opens after B_i returned. For the order claim: in T, after thread t's segment s come B_t(s) then
seg_t(s+1); the pending set P that contains seg_t(s) was emptied and run just before B_t(s)
(:2472-2474), and the next pending set starts with seg_t(s+1). Pending sets never contain parts from both
sides of a barrier. So listing P_0, B_0, P_1, ... with each P_i in T order enumerates T. QED.

### L4 (serializability). The execution of one iteration, with every lane phase scheduled arbitrarily, is trace-equivalent to the serial execution of T. Consequently the final state and every reply equal those of serial(T).

Proof. By L3 it is enough to show that one lane phase is trace-equivalent to serial(P_i, T). The lane
threads run concurrently, but each operation of a lane entry touches only that lane's hashtables (L1),
and the hashtables of different lanes are disjoint memory (O5), so any concurrent run of the lane
threads is equivalent to some interleaving of their operation sequences (there is no shared variable two
lanes both access, except the barrier word, so no data race decides a value). Any interleaving respects
each lane's internal order, which is T order (L2). Take such an interleaving I. Sort I stably into T
order by swapping adjacent pairs that are out of T order; such a pair is always from two different lanes
(same-lane pairs are already in T order), hence independent (L1), so each swap preserves the trace.
Therefore I is trace-equivalent to serial(P_i, T), and so has the same state and replies. Serial segments
are serial(P_i, T) by construction (fpSerialSegment walks the batches in order, :2370-2396). QED.

L4 gives G3 (every write to k is in T order, and T respects every client's order by O2 and the harvest
order), G4 for single-lane commands and for barriers (they run whole on one thread with nothing else
touching the keyspace), and the primary half of G8 once propagation order is shown to be T (L4b).

L4b (propagation order). After a lane phase, fpMergeLanes replays propagation "in T order: each part's
entries in its IO thread's harvest order" (:2225-2235) and a split entry's parts as one MULTI/EXEC
(fpFeedSplitPropagation :2173-2222); barriers propagate when they run on main, between the merges. So the
replication stream and AOF see the order P_0, B_0, P_1, ... in T order, which equals T (L3). The replica
applies that stream either serially or through its own plan (rpClassify repl_apply.c:178-206,
rpRunSegments :514-556), which has the same structure: one total order (the stream), lanes by
fastpathKeysShard, barriers on main between segments, a barrier re-check of observers. L1-L4 apply with T
= the stream order, so the replica's final state equals serial apply (G8 state equivalence). (O9: the
replica's segment numbering is global across chunks, k->base + e->seg, :409; O10: MSET parts wrapped as
MULTI/EXEC become one barrier on the replica, issue 25, so the replica never splits them.)

### L5 (split commands are atomic). A split MSET or MGET is observed by every other command as if it ran whole at its position in T.

Proof. Let X be a split entry in segment part (t, s) with parts X_1..X_p on lanes l_1..l_p. All parts have
seg = s (fpTrySplit copies `*e` into each part after `e->seg` was set by fpClassify :783, 737) so all run
in the same lane phase P_i (L3) (O11). Each X_j is a lane entry of lane l_j appended at X's harvest
position, so on lane l_j the operations of X_j sit at X's T position (L2). Let Y be any other entry. If Y
is a barrier or in another pending set, L3 orders Y entirely before or entirely after all of X. If Y is in
the same P_i: Y is a lane entry or a split entry; on every lane both X and Y have a part on, X_j and Y_j
run in the same relative order (both lanes use T), and on lanes where only one has a part there is nothing
to observe. So Y's reads of X's keys all see the state before X (if Y <_T X) or all after X (if X <_T Y),
and X's reads of Y's keys likewise. This is exactly the observation Y would make in serial(T). In the
serial fallback X runs whole on main. QED.

What L5 needs that is not obvious, and where it is checked:
- all parts in one segment (O11, :737 copies seg before the parts are pushed; the model variant V5
  breaks it and is caught);
- the same T position on every lane (L2; variant V1 breaks it and is caught);
- a key appears in exactly one part (keypart[i] is set once per key index, :704-712; a key named twice
  in one MSET goes twice into the same part, in command order, so last-write-wins is preserved);
- the reply is assembled from the parts in the command's key order (fpSplitAssemble :1203-1225, using
  keypart) and only when every part has a reply (:1189-1195);
- readers on other clients: see section 3.

### L6 (happens-before). Every write a lane performs in phase P_i happens-before every read main performs after the phase, and every write main (or an IO thread in READ) performs before the phase happens-before every read a lane performs in it; across lanes of different phases the relation is transitive through main.

Proof. phaseBarrierOpen stores the state word with memory_order_release (phase_barrier.c:95); a worker
returns the phase after loading it with memory_order_acquire (:145, :160), so main's prior stores (lane
vectors, fp_parts, fp_phase_time, keyspace writes by barriers) are visible to the worker (C11 7.17.3:
release/acquire on the same atomic object synchronizes). phaseBarrierDone does
atomic_fetch_sub(pending, 1, memory_order_acq_rel) (:177); main waits with an acquire load of pending
until it reads 0 (:105, :110-112). All the fetch_subs are RMWs on `pending`, so they form a release
sequence headed by main's release store of pending... main stores pending with memory_order_relaxed
(:94) but inside the mutex critical section that also publishes `state` with release; what matters is
that main's acquire load of 0 reads the value written by the last fetch_sub, and every RMW in the release
sequence of each worker's fetch_sub synchronizes with it (C11 5.1.2.4 / 7.17.3 p2-3: an RMW continues a
release sequence). So each lane's stores before phaseBarrierDone are visible to main after
phaseBarrierWaitAllDone. Lane i of phase P_i and lane j of phase P_{i+1} are ordered through main's
wait and open. IO threads' READ-phase stores (lane_ents, batches) reach main the same way (READ is a
barrier phase) and then lanes in WRITE through main's open. The data-race freedom this gives is what L4's
"any concurrent run equals some interleaving" needs (O7). QED. Variant V4 of the model drops this and lets
a barrier read the pre-phase state; it is caught.

A note on the stale comment at staged_loop.h:18-19 (design.md 2.3): it does not affect the proof, which
uses the barrier calls, not the comment.

### L7 (client order and reply order, G1 and G2). For one connection, commands execute in program order and replies are sent in program order.

Proof. In one iteration a client's commands are parsed by one thread into one batch in order (fpHarvest
:874-955, O2), so they are contiguous in H_t in program order, hence in T. The fast GETs answered in READ
are a leading run of GETs taken only when `fp_inflight == 0` (:956), that is when every earlier command of
the client has been executed and its reply delivered (fp_inflight is incremented at append, :870, and
decremented at delivery, :1254); so a fast GET precedes, in program order, everything of the client still
to be executed, and its linearization point (section L8) precedes theirs. Across iterations, iteration i's
commands are fully executed and replied before iteration i+1 reads (bulk-synchronous structure). Replies:
fast GET replies are written to the socket in READ (:964-966, fpSend appends behind any buffered bytes,
:1058-1064); batch replies are delivered in batch order per client in REPLY (fpDeliverRange :1233-1262)
and a STREAM worker delivers only prefixes up to the published `executed` count (:2724-2738), so the byte
order on the socket is program order. Requeued entries (returned to main unexecuted) are replayed in
front of anything parsed later (fpRequeue :1102; fix N1 made partial parses correct) (O12). QED.

### L8 (real-time order, G6). Define the linearization point of a lane write as the moment its lane applies it, of a barrier as its execution on main, of a fast GET as its read in the READ phase, and of a main-executed entry (a serial segment, the plain walk, or a STREAM-path run) as its execution. Then every command whose reply was sent before another command was received linearizes before it, and the linearization order within an iteration is T, or S on the STREAM path, and iteration order across iterations.

Proof. Let a be acknowledged (reply bytes written) before b is received. a's reply is written either in
READ (fast GET), in STREAM after a's execution, or in REPLY of a's iteration i. In all cases a's
linearization point is in iteration i at or before the write. b's bytes are read by an IO thread in some
READ phase; a READ phase that reads b must open after a's reply was written, so it is READ of an iteration
j > i or, for a fast GET a, j >= i with b read later in the same READ phase. Case j > i: b linearizes in
iteration j, after everything of i. Case j = i (a a fast GET): b is read in READ, so it is either a fast
GET (reads the same state S_i, same linearization point class; both are reads so their order is
irrelevant) or an entry executed in the write step after READ closed, hence after a. The linearization
order therefore respects acknowledgement-before-receipt, and within an iteration it is: fast GETs (all
read S_i, the state after iteration i-1's execution and the collect step's writes; no writer runs during
READ, O8), then T on the lane and plain paths. By L4 the replies equal those of this serial order, so it
is a valid linearization.

STREAM path. When the iteration runs no lane phase and a STREAM phase is open (section 1), main executes
the entries in S, the round-robin order over the threads' client runs, and a STREAM worker writes a
client's replies as soon as main has published the run that produced them, while main goes on executing
other runs. S is a legal linearization order for the iteration by the same argument: (1) S is executed by
one thread, so its state and replies are serial(E_i, S) by definition, with no trace argument needed; (2) S
keeps every client's program order, because a run is one client's consecutive batch entries and a run cut
by the prefetch window continues at the same cursor in the next round, so L7 holds under S; (3) every
entry of iteration i was received in READ of i, before any reply of i was written, so any two entries of i
are concurrent in the sense of linearizability and any serial order of them is legal, S included; (4) the
only replies that leave during the iteration are those of runs main has already executed, so a command b
received after seeing such a reply arrives in READ of a later iteration j > i and linearizes after
everything of i, exactly as in the case j > i above. Fast GETs read S_i as before. The replication stream
on this path is fed as each entry executes, so it carries S; the AOF is never fed on this path (a STREAM
phase does not open while the AOF is on), so L4b's statement about the AOF is about the lane and plain
paths only. QED.

Two consequences worth stating. (a) G6 across clients on different IO threads inside one iteration: two
commands received in the same iteration are concurrent (neither was acknowledged when the other was
received), so any order between them is legal, T on the lane and plain paths and S on the STREAM path. (b) The fast GET reads S_i even if a write to the same
key sits earlier in T in the same iteration from another client; that write was not acknowledged, so this
is legal, and the GET's own client has nothing in flight (L7).

## 3. The hard case: split MSET/MGET against readers on other clients during the lane phase

Who can read the keyspace while a lane phase runs?
1. Other lane entries of the same phase, on any lane, from any client and thread. These are ordered by
   T (L2) and see X whole (L5). This is where a reader on another client meets a split MSET: the reader's
   GET or MGET is itself a lane entry (GET is a lane command, fpKeysShard :612-615; MGET is split or one
   lane). Order between two different clients' entries is their T order, decided by thread index and
   harvest order at READ time, the same on every lane.
2. Main. It is blocked in phaseBarrierWaitAllDone (or running its own lane) for the whole phase
   (staged_loop.c:640-642). Non-fast-path clients served by ae run only in the write step's
   aeProcessEvents after fastpathStagedExecute returned (staged_loop.c:470-480, design.md 2.2 step 3).
3. IO threads doing something other than their lane: at the start of every phase a worker drains its job
   inboxes (io_threads.c:1343-1345). Those jobs are stock IO jobs: socket writes, deferred reads and
   parsing, frees of values already unlinked from the keyspace (freeValueNeverOnMain, io_threads.c:2313).
   None reads the keyspace (O18, asserted from the job list in design.md 5.2, not re-read here).
4. Fast GET: only in READ (fpSpeculate is called from fpRead :1002, READ phase only; depth 0). Not during
   WRITE.
5. STREAM workers: deliver reply bytes; closed before WRITE opens (staged_loop.c:637).
6. MAINT lanes, cron, eviction, active expire: all in other steps of the iteration (design.md 2.1-2.3).
7. A replica is a different process; the primary's stream is T order (L4b) and MSET parts are one
   MULTI/EXEC there (O10).

So nothing orders a reader against a split MSET except T, and T is a single total order realized
identically on every lane. There is no optimistic read, no version array and no validation step in this
branch (design.md 5.1: the D+ version arrays of the earlier dplus work are not present; "read safety comes
from phase separation"). The brief asked where the OCC validation sits: it does not exist and is not needed,
because the only speculative read (fast GET) runs while no writer exists.

Does anything rest on an unproven assumption? Yes, three things, all listed in OBLIGATIONS.md:
- O18 (IO-thread jobs never read the keyspace) is taken from design.md 5.2 and the job table, not from a
  fresh audit of every job type at HEAD.
- O5 (kvstore concurrent mode makes the per-shard tables disjoint memory, and kvstoreReconcile only folds
  counters) is taken from the design read of db.c:578-600 and kvstore.c; the hashtable code itself is
  unchanged versus upstream (design.md 5.1) and each table is owned by one lane, which is the condition the
  argument needs.
- The equality "operations of a lane entry touch only hashtables of its shard" (O3/O4) holds for the
  command set in fp_lane_commands as reviewed by W-B; a command that reads a key it does not declare
  (SORT BY pattern, a module command) would break L1. W-B's allowlist audit is the check; this worker did
  not re-verify all ~150 commands.

Also a precision about MSETNX, DEL, RENAME and the *STORE family across lanes: these are not split, they
are barriers (fpKeysShard returns -1 for keys in several shards; only MSET/MGET pass fpTrySplit). Their
atomicity is L3 (whole on main, nothing else running), which needs no further argument.

## 4. What this proof does not cover

- The C code itself beyond the lines cited: the proof is about the abstract plan. Memory safety, the
  correctness of cmd->proc under the lane executor (ectx, stats, errors), reply arena management, the
  requeue path's byte accounting, and client lifecycle are not modelled. W-C1/W-C2/W-F test those.
- The compiler and hardware: L6 cites the C11 model; it assumes the toolchain implements stdatomic
  correctly and that no plain (non-atomic) variable is shared between a lane and main without passing
  through a barrier (design.md 2.4 says fp_lanes_iter, fp_nlanes, fp_check_blocked rely on the barrier;
  the TSan runs of W-C1 are the check).
- Commands not in the abstract machine: hash field TTL commands, blocking commands, scripts, modules,
  streams, cluster slot lanes (lane = slot; fpTrySplit is off in cluster), SELECT inside a pipeline
  (O16: the entry carries its db, :860, but the lane key is shard only, so two dbs' shard s share lane
  s mod n; that is still a partition of (db, shard) pairs, so L1 holds).
- G7 (blocking and WATCH): only the part needed for G5 is argued: a key that is watched or blocked on at
  READ time makes its commands barriers (fpKeyObserved :602-606, sampled flags :1750-1752), and a barrier
  that creates a new observer makes the rest of the iteration serial (fastpathKeyObserversChanged :2460,
  :2481; the issue-29 fix, variant V6 of the model). FIFO wakeup order and exactly-once service are
  W-H's subject.
- G9 (AOF order and fsync point), G10 (expiry legality), G11 (notifications): lanes are disallowed when
  keyspace notifications, tracking or a module observer are on (fpLanesAllowed :1720-1738); AOF order
  follows L4b on the lane path and the execution order T on the plain path (the STREAM path never feeds
  the AOF); the fsync-before-reply point (aof-always step before REPLY, staged_loop.c:527-530) is
  stated, not proven here.
- The STREAM path's executor as code: L8's STREAM paragraph argues from four properties of
  fastpathStagedExecuteStreaming (one executing thread, whole client runs in order, replies only for
  published runs, propagation in execution order) that were read in the code at S1, F and C
  (the correctness review, not published here: section 2 item 3b and 5.3 STREAM-ORDER) and
  are not exercised by the differential test, whose plain executor is the T walk.
- Liveness, fairness, and performance: nothing here.
- The model (section MODEL-RESULTS.md) explores all interleavings of per-key steps for small instances,
  which assumes a per-key step is atomic. A hashtable operation on one shard by one thread is atomic
  with respect to other shards (no shared memory), which is what the assumption encodes; it is not a
  statement about the hashtable internals.
