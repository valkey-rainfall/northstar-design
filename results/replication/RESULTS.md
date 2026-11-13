# Cross-host replication results (the test hosts, real NIC), 2026-10-31

Every statement here is a finding for the exact configuration in README.md and FINDING-ack-timeout.md, not a general
conclusion. Per-run table: summary.md / summary.tsv (scripts/analyse.py). Raw data: runs/.

## Fixed-rate SET stream, base config (lanes forced, repl-stream-sender yes, replica-parallel-apply yes), 60 s
| offered SET/s | S1 achieved (3 reps) | P9 achieved (3 reps) | stream MB/s | replica lag | ACK lag max | timeouts | ENA deltas |
|---:|---|---|---:|---|---:|---:|---|
| 50,000 | 49,999-50,000 | 49,999-50,000 | 3.0 | below sampling resolution (~3 ms) | <= 1 s | 0 | 0 on all hosts |
| 200,000 | 199,999-200,000 | 199,999-200,000 | 11.8 | below resolution | <= 2 s | 0 | 0 |
| 500,000 | 499,999-500,000 | 499,999 | 29.5 | below resolution | <= 1 s | 0 | 0 |
| 1,000,000 | 999,998-1,000,000 | 999,998-1,000,000 | 59.0 | below resolution | <= 1 s | 0 | 0 |
| closed loop | 2.73-2.75M | 2.73-2.74M | ~161 | 0 (in step) | 58-61 s | yes, every ~60 s | 0 |

- S1 and P9 behave the same at every rate (achieved rate equal within 0.1%, same lag behaviour).
- The replication flow stays far below the EC2 single-flow limit (161 MB/s = 1.3 Gb/s vs about 9.5 Gb/s); the ENA
  allowance counters did not move on any host in any run, so no rep was dropped for network limits.
- Digests: equal in every run where replica and primary offsets were equal at the end (34 of 34). The earlier WAIT
  timings are invalid (harness bug, see FINDING-ack-timeout.md).

## Closed-loop controls (one run each): see FINDING-ack-timeout.md
The ACK timeout appears with replica-parallel-apply yes (base, nosender) and not with it off (noapply, nolanes,
where the replica instead falls 5.5-8.9 GB behind) and not on STOCK (1.40M SET/s, replica in step). Replica sends
the ACKs and its TCP stack sees them acknowledged; the primary process does not read them while its replica
connection has only a small output backlog.

## Replica reader during a 500k SET/s stream (one run per commit; compare with finding P3)
| run | writer SET/s | reader GET/s at replica (400 conns, P1, 16 threads) | GET p50 us | p99 us | p999 us |
|---|---:|---:|---:|---:|---:|
| S1-500k-r1-reader | 499,999 | 1,372,316 | 280 | 364 | 450 |
| P9-500k-r1-reader | 500,000 | 1,372,043 | 280 | 368 | 462 |
- S1 and P9 are the same within one run each. A reader-only baseline (no write stream) was not run, so these numbers
  do not yet say how much the apply stream costs the reader; P3 concerned an MSET-heavy stream, this is SET only.

## Not done here
- Rates between 1M and 2.7M SET/s (where the ACK problem starts).
- Reader-only baseline at the replica; MSET-heavy stream for P3.
- STOCK at fixed rates (only closed-loop STOCK controls were run).
