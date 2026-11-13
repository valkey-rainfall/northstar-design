# Cross-host replication harness (manual)

Replication measured over the real NIC with three hosts. Script: scripts/xh.py (ssh to the three hosts
from a control host; host names, addresses and the key file come from the environment, see the script
docstring). Per-run analysis: scripts/analyse.py, which writes summary.md and summary.tsv.

## Topology

| role | instance type | address (placeholder) | port | cpus | build |
|---|---|---|---|---|---|
| primary | c8gn.metal-24xl | 198.51.100.10 | 51000 | taskset 0-7 | ~/xh/<label>/valkey-server |
| replica | c8gn.metal-24xl | 198.51.100.11 | 51001 | taskset 0-7 | ~/xh/<label>/valkey-server |
| writer | c8gn.48xlarge | 198.51.100.12 | - | 16-47 (32 threads, 2400 conns, P10) | cachecannon e545c26 |
| reader (reader runs only) | c8gn.48xlarge | - | - | 48-63 (16 threads, 400 conns, P1) | cachecannon e545c26 |

The three hosts are in one cluster placement group. Builds: S1 92709489, P9 91dbb9c3, STOCK 2a23bcda,
the same binary files on the primary and the replica.

## Server args

- both: --save '' --appendonly no --protected-mode no --enable-debug-command yes
  --client-output-buffer-limit 'replica 0 0 0' --repl-backlog-size 1gb --io-threads 5, bound to the private
  address only (the output buffer limit is off so a lagging replica is measured as lag, not disconnected)
- primary: --io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes
- replica: --replica-parallel-apply yes
- Data dir in /dev/shm, removed after each run.

## Per run

Fresh pair -> REPLICAOF -> wait for the link -> INFO t0 -> ENA counters t0 (all three hosts) -> sampler on
the primary host (1 s: master_repl_offset, the slave0 line, the replica's slave_repl_offset, ss -tin of
the replication flow) -> cachecannon SET stream, prefill 3M keys, then 5 s warmup and 60 s at the offered
rate -> ENA t1 -> INFO t1 -> WAIT 1 60000 -> DEBUG DIGEST on both -> SHUTDOWN NOSAVE.
Matrix: rates 50k, 200k, 500k, 1M SET/s and closed loop (max); 3 reps; S1 and P9 alternate inside each rate.
Reader runs: a 500k SET/s writer plus a GET reader at the replica (P1, 400 conns) starting 10 s later, one
per build.

## Files

- RESULTS.md: the results and what they show.
- FINDING-ack-timeout.md: replica ACKs stop under a closed-loop stream with replica-parallel-apply yes.
- PROBE-RESULT.md, FIX-VERIFY.md: the diagnosis of that finding and the check of its fix.
- summary.md, summary.tsv: one row per run. The raw run directories (INFO, samples, logs) are not
  published here.
