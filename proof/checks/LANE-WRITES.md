# What lane code writes: the static list behind item 3

Revision: C = ceaa1101d (branch northstar/proof-checks adds only checks). Method: grep of the lane-side
region of src/fastpath.c (fpLaneCall, fpLaneExecute, fastpathStagedWriteLane, fastpathStreamLaneCall,
lines 2206-2560 at b4729b678) for writes to file-scope or server-wide names, plus a grep of the files
that implement the 124 lane commands (t_string.c, t_hash.c, t_set.c, t_zset.c, t_list.c, db.c, expire.c,
object.c, lrulfu.c) for `server.<field> =, +=, ++`. Call-graph completeness is NOT established by this
list; TSan (tsan/) is the dynamic check of whatever the list misses.

## 1. Thread-local (one per thread, never shared)

| Variable | File | Written by lane code |
|---|---|---|
| `ectx` (points to `&L->ctx`, the lane's execContext) | server.c:120 | set on entry, restored on exit |
| `exec_lane` | server.c:121 | 1 inside the lane |
| `fp_cur_lane`, `fp_exec_entry`, `fp_stream_pos` | fastpath.c | set per phase / per entry |
| `lane_batch` (prefetch batch) | memory_prefetch.c:63 | prefetchLaneBatchUse |
| `lrulfu_rng`, `fastget_touch_rng` | lrulfu.c, fastget.c | LFU increments |
| `listpack_ttl_ignored` | t_hash.c:149 | hash field expiry |
| `repl_apply_in_lane`, `repl_apply_plan_lane`, `repl_apply_key`, `repl_apply_shard` | repl_apply.c | replica lanes |
| `kvs_owned_mod/lane/only` (STAGED_CHECKS only) | kvstore.c | this branch |

execContext fields written per command (all per lane, folded by main after the phase in fpMergeLanes):
dirty, current_client, executing_client, execution_nesting, in_call, cmd_time_snapshot,
also_propagate, lazy_expire_disabled, stat_numcommands, stat_keyspace_hits, stat_keyspace_misses,
stat_expiredkeys, stat_expiredfields, stat_total_error_replies, prev_err_count (server.h:1786-1802).
At C the matching `server.stat_*` and `server.dirty` writers are gone from the lane command files
(grep found none; the only `server.` writes left there are `server.replication_allowed` in db.c, set by
SWAPDB/FLUSHALL which are barrier entries, and the active-expire cycle statistics in expire.c, run by
cron or MAINT).

## 2. Per-lane structures (fp_lanes[l], disjoint by lane; read by main only after the barrier)

The executor client `L->ec` and its reply buffers; the reply arena chunks (`L->chunks`, `L->used`);
the run list and cursors (`L->run`, `L->cursor[tid]`); counters `executed`, `prefetches`, `dur_cnt/sum/max`;
command stats (`fpLaneCmdStat`), error and latency samples (`fastpathLaneLatencySample`, latency.c:78),
commandlog records; propagation frames (`L->frames`, `L->largs`); the lane execContext `L->ctx`.

## 3. Per-partition keyspace memory (disjoint by the lane's partitions; item 2 checks this)

The hashtables of `db->keys`, `db->expires`, `db->keys_with_volatile_items` with
`didx % nlanes == lane`, their entries and values, and the per-table concurrent-mode deltas in the
table metadata (`kvstoreHashtableMetadata`: dirty, key_delta, bucket_delta, overhead deltas,
alloc_delta, defer_free). LRU/LFU header words of the objects a lane command touches (CAS).

## 4. Shared memory written from lanes, with atomics (not plain)

| Variable | Synchronization |
|---|---|
| `kvs->dirty_count` and the slot it claims in `kvs->dirty_tables[]` | `atomic_fetch_add` relaxed; main reads after the barrier (acquire on `pending`) |
| phase barrier words `state`, `pending` | release/acquire (phase_barrier.c) |
| zmalloc `used_memory` | atomic |
| `server.lazyfree_pending_objects`, lazy-free counters | atomic |

## 5. Shared plain variables lanes READ that main writes before the phase (must cross the barrier)

`fp_lanes_iter`, `fp_nlanes`, `fp_lane_main`, `fp_parts[]`, `fp_nparts`, `fp_prop_mode`,
`fp_phase_time`, `fp_phase_mono`, `fp_phase_us`, `fp_phase_fresh_mono`, `fp_check_blocked`,
`fp_check_watched`, the threads' `lane_ents[lane][]`, `lane_n[lane]`, the entries themselves (argv,
cmd, db, shard, seg), `server.*` configuration fields, the command table, `db->watched_keys` and
`db->blocking_keys` (read by the STAGED_CHECKS re-check), the keyspace (all partitions, for reads of
the lane's own partitions only).

All of these are written by main before `phaseBarrierOpen` (release) and read after
`phaseBarrierAwaitPhase` (acquire), or written by lanes before `phaseBarrierDone` (acq_rel fetch_sub)
and read by main after `phaseBarrierWaitAllDone` (acquire). TSan models every one of these operations
(C11 atomics with explicit orders and the pthread mutex/condvar fallback), so a plain variable that
misses the barrier is reportable; mutation m3a shows one being reported. The two `atomic_thread_fence`
calls in fastpath.c:313 (ACL admission quiesce) and staged_loop.c:605 (deferred read) are outside the
lane phases; TSan cannot see fences, so a race that depended only on them would be a false report, not
a missed one.
