# North Star design: evidence

This repository holds the evidence behind the North Star design document for Valkey: a phased event
loop with fast reads on IO threads and parallel write lanes, so that one server process can use many
cores. The design document itself is not here yet (see docs/README.md). Every number, figure and
correctness claim in the document should be traceable to a file in this repository, or to a public
commit of the code.

What is here:

| Directory | Content |
|---|---|
| results/ | Throughput and latency measurements on two EC2 hosts: the reference load, the IO-thread sweeps of Figures 1 and 2, the collector-thread runs, the AOF cell, the seqlock comparison, the cross-host replication runs, the network counters |
| proof/ | The proof (lemmas and obligations), the TLA+ and Python models with their logs, and the proof checks run on C (checks built into the server, mutations, ThreadSanitizer, STREAM coverage) |
| tests/ | The differential test of the write lanes, the black-box linearizability harness and its histories, the reply-order probe, test hooks and mutation patches |
| figures/ | Every figure of the design document (PNG and SVG) and the scripts that draw them |
| docs/ | Place for the design document |

## Builds

Every build except ORIG is a public commit in [valkey-rainfall/valkey](https://github.com/valkey-rainfall/valkey).
Builds marked with a tag can be fetched by that tag (`git fetch <remote> tag northstar/c`); the others by
commit id. STOCK is on the unstable branch of the Valkey project.

| Label | Commit | Tag or link | What it is |
|---|---|---|---|
| C (also CONS) | ceaa1101d | [northstar/c](https://github.com/valkey-rainfall/valkey/tree/northstar/c) | The frozen proof-of-concept commit the design document is based on |
| STOCK | 2a23bcda0 | unstable branch of the Valkey project | The unmodified server, unstable branch, 2026-10-19 |
| S1 | 927094894 | [northstar/s1](https://github.com/valkey-rainfall/valkey/tree/northstar/s1) | The original revision of the proof of concept |
| PRE-C | c8b06eb0f | [commit](https://github.com/valkey-rainfall/valkey/commit/c8b06eb0f) | The revision just before C (C without its own 13 commits) |
| CFIX, CFIX-N6 | d7bf1a4cd, 77e034db8 | [branch pr/consolidated-fixes](https://github.com/valkey-rainfall/valkey/tree/pr/consolidated-fixes) | Two commits of the fixes branch on top of C (31 commits, not merged) |
| SEQ | 59674df38 | [northstar/seq](https://github.com/valkey-rainfall/valkey/tree/northstar/seq) | The PR-ready port of the seqlock design (concurrent reads with validation) |
| ORIG | not published | - | The original build of the seqlock design; its commit is not on a public branch, so P23 cites it by label only |
| P9, FIX, PROBE | 91dbb9c3, f65f429e, e82fc7da | [P9](https://github.com/valkey-rainfall/valkey/commit/91dbb9c3), [FIX](https://github.com/valkey-rainfall/valkey/commit/f65f429e), [PROBE base](https://github.com/valkey-rainfall/valkey/commit/e82fc7da) | Test builds on S1 used in the replication runs (S1 plus some fixes of design doc section 9) |
| F | f01d005ea | [northstar/f](https://github.com/valkey-rainfall/valkey/tree/northstar/f) | The revision the correctness review was frozen at |
| PRFIX | 8cbc82360 | [northstar/prfix](https://github.com/valkey-rainfall/valkey/tree/northstar/prfix) | F plus the review's fix and test commits |
| Difftest port | 6ba80d232 | [northstar/difftest-port](https://github.com/valkey-rainfall/valkey/tree/northstar/difftest-port) | The lane differential test ported to PRFIX (tests/difftest) |
| Test seams | e24a4ccf1, 0f2ac30ae, 4bb8dc344 | [northstar/seam-ready-registry](https://github.com/valkey-rainfall/valkey/tree/northstar/seam-ready-registry), [northstar/seam-replapply](https://github.com/valkey-rainfall/valkey/tree/northstar/seam-replapply), [northstar/seam-init-once](https://github.com/valkey-rainfall/valkey/tree/northstar/seam-init-once) | The three test-only commits cherry-picked onto C for the differential test on C (tests/difftest/on-C) |
| Proof checks | 8a1e6c1b4 and the commits below it | [branch northstar/proof-checks](https://github.com/valkey-rainfall/valkey/tree/northstar/proof-checks) | The checks of the proof's assumed obligations, on C (proof/checks) |
| HEAD (proof, models, linearize) | 1fb18b7d | [commit](https://github.com/valkey-rainfall/valkey/commit/1fb18b7d25e043f1a94794eeb9957d75a7becf9f) | The earlier revision the proof, the models, the first differential test and the linearizability runs studied |

The load generator is cachecannon (public); the build used is named with each result (82a79d0 for
Figures 1 and 2, e545c26 for the reference load, 1bea936b = release 0.0.34 for P23).

## How the evidence maps to the design document

Section numbers are those of the design document draft.

| Doc section | Claim | Evidence |
|---|---|---|
| 1, Figure 1; 6.4 | GET 16 B: C 199.96 M ops/s at io-threads 62 against STOCK 3.59 M | results/p21.md "Figure 1 sweep"; figures/fig1_scaling.py |
| 6.4 | Generator is not the limit; two client layouts agree; background process effect | results/p21.md "Generator calibration", "Figure 1 sweep" (control row), "A/B" |
| 1, Figure 2; 6.3 | SET 16 B: C 43.38 M at 62 against STOCK 2.47 M; below stock at 1 and 2 IO threads | results/p22.md "Step 2"; results/p22/set-sweep.txt; figures/fig2_set_scaling.py |
| 6.1 | Network allowance counters unchanged in 578 tasks | results/ena/ena-per-task.tsv |
| 6.1, 12.3 | AOF cell (SET with appendfsync everysec) and its stalls | results/p21.md "AOF9 cell"; results/p21/aof9-per-rep.tsv |
| 6.2 | Reference load: STOCK 3.30 M, C 12.49 M (defaults), 17.48 M (collector thread) | results/p21.md "STOCK at io-threads 9", "Consolidated branch and stock point", "CONS with the epoll thread" |
| 6.2, 9 | Collector-thread cost at io-threads 10 and 11 | results/p22.md "Step 3b", "Step 4"; results/p22/matrix.txt, io11.txt |
| 6.3, 12.3 | The S1 campaign (other value sizes, SET, mixed, io-threads 1) | results/p19-s1-campaign.md |
| 6.3 | Fixed-rate latency on C | results/p23.md "P23d", step 2 |
| 7 | Seqlock design against C | results/p23.md; results/p23/ |
| 12.3 | Bisect of the collector-thread cost, shard diagnostic, start check below io-threads 3 | results/p21.md "Bisect", "Diagnostic", "Epoll thread test", "Finding" |
| 4.9.2 - 4.9.4 | Cross-host replication runs, replica ACK timeout and its fix, one-flow cap | results/replication/; results/one-flow-cap.md; figures/fig8_repl_stream.py |
| 5.3 | Proof: lemmas and obligations | proof/PROOF.md, proof/OBLIGATIONS.md |
| 5.3 | Model checking (TLA+, Python model) | proof/tla/, proof/model/, proof/MODEL-RESULTS.md |
| 5.3 | Checks of the assumed obligations on C; STREAM coverage | proof/checks/STATUS.md, proof/checks/STREAM-S.md |
| 5.3 | Differential test, 42,000 programs, four mutations | tests/difftest/ |
| 5.3 | Linearizability, 66 histories, 0 violations | tests/linearize/ |
| 5.3, 12.3 | Reply-order probe on C | tests/probe/ |
| 4 | Figures 3 to 7, 9 and 10 | figures/fig_timelines.py, figures/fig10_roadmap_dag.py |

## How to reproduce

- Throughput: results/README.md gives the hosts, the server command line and the generator
  configuration. Each result file names its build, cell, task count and order.
- Proof and models: proof/REPRODUCE.md (no build needed for the citations; TLC and Python for the
  models). Proof checks on C: proof/checks/REPRODUCE.md.
- Tests: tests/difftest/REPRODUCE.md, tests/linearize/REPRODUCE.md, tests/probe/run-probe.sh.
- Figures: `python3 figures/<script>.py` with matplotlib (Figure 10 also needs graphviz `dot`).

## Not in this repository yet

Some evidence the design document cites has no public copy yet: the October 2026 campaign on an
earlier revision (design doc 6.4 and 12.3), the loopback costs, the everysec kill test, the AOF review
notes, the earlier measurements of thread-owned clients and of the transport build, the
instruction-count profile, the suite counts on C plus the fixes branch, and the correctness review
that some files here cite as "the correctness review" or SECTION.md. The runner's per-task records
(named by task ids such as 2026.11.07_04.19.30.413057) are not published either.

## Credits

- Rain Valentine and Dante Knowles, authors. Dante Knowles built the proof of concept that the design
  document describes.
- Uri Yagelnik and Dan Touitou, for the read offload of valkey issue 2022, which the design document
  compares as an alternative.

## Licence

BSD-3-Clause, the licence of Valkey. See [LICENSE](LICENSE).
