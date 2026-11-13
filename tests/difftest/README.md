# Phase 23b: the lane differential test at F

The Phase 6 differential test (FastpathDifftest, 42,000 seeds, three executors) and six of the FIX
FastpathLanesTest tests, ported onto PRFIX (F f01d005ea plus our fixes) as commit
6ba80d232 with a fourth executor for F's lane key prefetch. Test code only.

- STATUS.md: what was ported and adapted, what was left out and why, the results (42,000 seeds x 4
  executors pass; 4 of 4 mutations caught; lanes x20; 14 suites shuffled x20; ASAN), the window probe.
- REPRODUCE.md: build and run commands.
- 0001-test-port-difftest.patch: the commit. mutate_f.py: the four production mutations for F.
- run-main.sh, run-mut.sh, build-asan.sh: the exact run scripts. logs/: the run logs.

This run turns the "carried" marks of the correctness review (SECTION.md, not published) section 3 that the
difftest and the lanes tests cover into "at F" (SECTION.md change log, 2026-11-06).
