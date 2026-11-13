#!/usr/bin/env python3
# Mutation m3a: main reads a lane-written plain field (fp_lanes[l].executed) while the WRITE phase is
# open, between phaseBarrierOpen and phaseBarrierWaitAllDone, instead of after the barrier. This is the
# shape of a stats read placed one line too early. TSan must report the race between the lane thread's
# L->executed++ (fpLaneExecute) and main's read.
f = "src/fastpath.c"
s = open(f).read()
old = """/* Main, after a write or apply phase: the position in command order of a lane record."""
new = """/* MUTATION m3a: main peeks at the lanes' counters while the phase is open. */
long long fastpathMutationPeekLanes(void) {
    long long sum = 0;
    for (int l = 0; l < fp_nlanes; l++) sum += fp_lanes[l].executed;
    return sum;
}

/* Main, after a write or apply phase: the position in command order of a lane record."""
assert s.count(old) == 1
open(f, "w").write(s.replace(old, new))

f = "src/staged_loop.c"
s = open(f).read()
old = """    int rc = phaseBarrierOpen(&sl_barrier, STAGED_PHASE_WRITE);
    serverAssert(rc == 0);
    sl_opens++;
    if (sl_main_lane) fastpathStagedWriteLane(0);
    phaseBarrierWaitAllDone(&sl_barrier, sl_main_spins);
    stagedAccountPhase(STAGED_PHASE_WRITE, sl_workers);
"""
new = """    int rc = phaseBarrierOpen(&sl_barrier, STAGED_PHASE_WRITE);
    serverAssert(rc == 0);
    sl_opens++;
    if (sl_main_lane) fastpathStagedWriteLane(0);
    extern long long fastpathMutationPeekLanes(void);
    sl_mutation_sink += fastpathMutationPeekLanes(); /* MUTATION m3a: before the barrier closes */
    phaseBarrierWaitAllDone(&sl_barrier, sl_main_spins);
    stagedAccountPhase(STAGED_PHASE_WRITE, sl_workers);
"""
assert s.count(old) == 1
s = s.replace(old, new)
old2 = "void stagedRunWritePhase(void) {\n"
s = s.replace(old2, "static long long sl_mutation_sink; /* MUTATION m3a */\n" + old2, 1)
open(f, "w").write(s)
print("m3a applied")
