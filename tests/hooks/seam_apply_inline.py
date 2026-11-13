#!/usr/bin/env python3
"""Seam for a replica-apply differential test: run APPLY (and PARSE) lane phases inline when unit tests
enabled inline lanes with testOnlyStagedSetWorkers. Mirrors the existing write-phase seam. Run from the
worktree; produces the change in src/staged_loop.c."""
p = 'src/staged_loop.c'
s = open(p).read()
old = """void stagedRunLanePhase(int phase, int with_workers) {
    stagedStreamClose(1); /* a phase opening while a stream is open means main is mid-exec: abort it */
    if (!with_workers) {"""
new = """void stagedRunLanePhase(int phase, int with_workers) {
    if (sl_inline_lanes) {
        /* Unit tests: no worker is enrolled; run every lane of this phase here, lane by lane, in lane
         * order (the replica plan's PARSE and APPLY phases included). */
        for (int tid = sl_main_lane ? 0 : 1; tid <= sl_workers; tid++) stagedRunLane(phase, tid);
        return;
    }
    stagedStreamClose(1); /* a phase opening while a stream is open means main is mid-exec: abort it */
    if (!with_workers) {"""
assert s.count(old) == 1
s = s.replace(old, new)
open(p, 'w').write(s)
print("seam applied")
