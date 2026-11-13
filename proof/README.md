# W-A `proof`: mathematical argument and executable model for write-lane ordering

STATUS: complete (2026-10-29 05:12 UTC; 24 minutes wall clock)

Revision under study: HEAD = origin/audit/issue29-counter-recheck (1fb18b7d), with
S1 = 927094894 named where the two differ.

Files:
- PROOF.md: abstract machine, lemmas L1-L8 with proofs, what is not covered.
- OBLIGATIONS.md: proof obligations tied to code lines, with status.
- model/lanes_model.py: exhaustive-interleaving checker for G1-G6, with broken variants.
- MODEL-RESULTS.md: what the model checked and what it found.
- tla/Lanes.tla, tla/MC1.tla, tla/MC2.tla, tla/run_tlc.sh, tla/tlc-*.log: TLA+ spec of one iteration, two
  instances, driver and raw TLC output (correct: no error; 4 broken variants: counterexamples).
- MODEL-RUN.log, MODEL-RUN-seeds80.log: raw Python model output.
- REPRODUCE.md: steps from a fresh clone.

## Summary

- Proven (relative to the obligations): L1-L8 in PROOF.md. The lane plan is trace-equivalent to the serial
  execution of the harvest order T; split MSET/MGET are atomic because all parts share one T position and
  one segment; readers on other clients during a lane phase are lane entries themselves, ordered by T;
  nothing else reads the keyspace during a WRITE phase; fast GET reads a quiescent state with nothing in
  flight for its client; happens-before comes from release/acquire on the phase barrier.
- Tested by model: Python (G1-G6, 2 iterations, fast GET, WATCH/EXEC): correct clean over 2061 executions
  of 85 scenarios; 6 broken variants all caught. TLC: 2 instances, correct clean, 4 broken variants caught.
- Assumed (OBLIGATIONS.md): O1 (lane allowlist declares all keys; W-B), O5 (kvstore concurrent mode is a
  memory partition; design.md), O7 completeness (every plain shared variable passes a barrier; TSan runs),
  O15 completeness (the observer denylist in fpLanesAllowed is complete).
- At S1 only: O12 (requeue order, fix N1) and O17 (issue-29 recheck) fail, so G2 and G5 do not hold at S1.
- Not covered: the C code beyond the cited lines, compiler and hardware, blocking/G7 details, G9-G11,
  cluster slot lanes, replica fast GET, serial-fallback segments in the models.
- Weak points worth a reviewer's attention: (1) the proof depends on a denylist (fpLanesAllowed) and an
  allowlist (fp_lane_commands) both maintained by hand; (2) O18 says no IO-thread job may read the keyspace,
  which nothing enforces; (3) the design.md description "T order" is right, but only because fpExecuteWithLanes
  accumulates pending parts across thread boundaries (thread 0's last segment and thread 1's first run in one
  phase); a change to that loop that ran each thread's segments separately would still be correct, while one
  that ran barriers of two threads back to back before their segments would not.
