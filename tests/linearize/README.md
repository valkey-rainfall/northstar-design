# W-C2 linearize: black-box linearizability check of the write lanes

Revision under test: HEAD = `origin/audit/issue29-counter-recheck` (1fb18b7d25e043f1a94794eeb9957d75a7becf9f).
Every claim below is about this revision unless it says "baseline" (same binary, io-threads 1, fast path off: the
stock code path) or "mutant" (HEAD plus `mutation-reverse-lane-order.patch`).

Verdict in one line: in 30 lanes-on histories (8 clients, pipelined and not, 10 s each, lane entries engaged every
time), 30 baseline histories and 6 primary+replica histories the checker found NO violation of per-key
linearizability (G3, G6), per-connection order (G1, G2), MSET/MGET/MSETNX/DEL-many/RENAME atomicity (G4),
MULTI/EVAL transfer atomicity (G5) or replica read-after-WAIT (G8). The same checker rejects a mutated server
(per-thread lane order reversed inside a segment) on every pipelined history. See STATUS.md for the tables.

## What is checked (the specification)

The checker (`tests/linearize/harness/checker.py`) treats the server as a black box and checks a recorded history, where
every operation has an invoke time (just before the request bytes are written) and a complete time (just after the
reply is parsed), both `time.monotonic_ns()` on the client host. Conservative timestamps (taken outside the socket
calls) only widen the concurrency window, so they never produce a false violation.

1. Linearizability per object (Wing and Gong search with Lowe's cache of failed (set, state) configurations):
   - objects are every single key (SET/GET/DEL/APPEND/INCR; MSET, MGET, MSETNX and DEL-many are projected to
     one sub-operation per key with the same timestamps), and every declared key GROUP as one tuple-valued object
     (the 4-key snapshot group with MSET/MGET/MSETNX/DEL-many, the 2-key pair with RENAME in both directions plus
     SET/GET/DEL on its members). The group object is the strong form of the "atomic snapshot" check: an MGET must
     return the state after some prefix of the group's write sequence, and that prefix must respect real time.
   - program order inside one connection is enforced: a pipelined command may be linearized only after the earlier
     commands of its connection (this is what G1/G2 add on top of real-time order).
   - the front walk is exact and incremental (ops sorted by invoke time, running minimum of complete time), so a
     10 s history with 100k operations is checked in a few seconds.
2. Snapshot check (cheap, independent of the search): every MGET over the whole snapshot group is all-nil or all one
   token (each MSET writes one token "c<client>:<seq>" to all 4 keys; DEL-many clears all 4).
3. Transfer-sum invariant: every MGET over the 4 account keys sums to 400 while MULTI DECRBY/INCRBY EXEC and
   EVAL transfers run concurrently (G5 atomicity and isolation seen by other clients).
4. Replica check: SET k v on the primary, WAIT 1 0, then GET k on the replica must return v (G8 read-after-WAIT).

Keys of one group are chosen so that they fall in pairwise distinct keyspace shards (Python copy of
keyspaceShard(), `keyspace_shard_bits` read from INFO = 8), so every MSET/MGET/RENAME/DEL-many is a cross-lane
command that the lane path must split into parts and reassemble.

The checker is itself tested (`selftest.py`): 16 hand-made histories, 8 that must pass and 8 that must fail
(stale read, the classic two-reader non-linearizable history, lost INCR update, torn MGET, stale MGET snapshot,
two MSETNX winners, non-atomic RENAME, broken pipeline order). All 16 behave as expected.

## What is NOT covered (honest limits)

- Linearizability is checked per object (key or declared group). Cross-object real-time order between two
  unrelated single keys is not checked (no test writes to r0 then expects a later read of r1 to be ordered); the
  group objects cover the multi-key commands the brief names.
- Account keys are excluded from the per-key check (their values change through transfers that are recorded as one
  operation); the transfer check is the sum invariant plus the EXEC/EVAL reply count, not a full linearizability
  check of the account object.
- The mutant is detected only through pipelines: inside one lane segment the entries of different clients are
  concurrent in real time, so any order among them is a legal linearization. A reordering bug that never reorders
  one connection's own commands and never crosses a segment boundary is invisible to a black-box history checker by
  definition (it is not a bug under the specification). The unit-level difftest (W-C1) is the right tool for that.
- Timing: the Python driver holds the GIL, so the recorded concurrency window is wide and the front (max number
  of concurrent operations) stays small (6-8); the search never hit its step budget.
- No cluster mode, no AOF, no eviction/expiry in these histories.

## Files

- `../../tests/linearize/harness/driver.py`   history recorder (standard library, raw sockets)
- `../../tests/linearize/harness/checker.py`  the checker; `selftest.py` its self-tests; `resp.py` RESP helper
- `../../tests/linearize/harness/server.sh`, `run_matrix.sh`  server start/stop and the 30-history matrix
- `mutation-reverse-lane-order.patch`  the mutated server (git diff against 1fb18b7d)
- `results/`  summary tables, per-history .meta (config, key shards, engagement delta) and .check output, gzipped
  histories that back the mutant failure and the pass counts, sha.txt with full revisions and toolchain
- `REPRODUCE.md`  steps from a fresh clone
- `STATUS.md`  result tables, pass counts, engagement counters, not-done list
