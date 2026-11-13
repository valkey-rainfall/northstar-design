# Finding (not a conclusion): replica ACKs stop under a closed-loop SET stream with replica-parallel-apply yes

Status 2026-10-31 02:15 UTC. Measured on the test hosts over the real NIC with scripts/xh.py.
Raw data: runs/<name>/ (run.json, samples.txt, writer.out, primary.log, replica.log, diag-*.txt).

## Exact configuration
- Primary: server-host (c8gn.metal-24xl), 198.51.100.10:51000, `taskset -c 0-7`. Replica: replica-host
  (c8gn.metal-24xl), 198.51.100.11:51001, `taskset -c 0-7`. Same AMI, cluster placement group, MTU 9001, RTT ~0.1 ms.
- Both: `--save '' --appendonly no --protected-mode no --enable-debug-command yes --client-output-buffer-limit
  'replica 0 0 0' --repl-backlog-size 1gb --io-threads 5`, data dir in /dev/shm, repl-timeout default (60 s).
- Variants (primary args / replica args):
  - base: `--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes` /
    `--replica-parallel-apply yes`
  - noapply: same primary / `--replica-parallel-apply no`
  - nosender: `--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender no` /
    `--replica-parallel-apply yes`
  - nolanes: `--repl-stream-sender no` / `--replica-parallel-apply no`
  - stock: none (STOCK build 2a23bcda0 only)
- Writer: cachecannon e545c26 on client-host cpus 16-47, 32 threads, 2400 connections, pipeline 10, SET 100%,
  16 B keys and values, 3M keys, prefill, 5 s warmup, 60 s closed loop (no rate limit).
- Builds: the runner build cache binaries, sha256 in binaries.json. S1 92709489, P9 91dbb9c3, STOCK 2a23bcda.

## Observations (closed loop, one run each unless noted)
| run | writer SET/s | primary drops replica as timed out | max ACK lag (slave0 lag=) | replica stream lag at end |
|---|---:|---:|---:|---:|
| S1 base (r1, r2, r11), P9 base (r1-r3) | 2.73-2.75M | yes, about every 60 s | 60-61 s | 0 (in step) |
| S1 nosender (r11) | 2,755,422 | yes (1 in the window) | 61 s | 0 (in step) |
| S1 noapply (r11) | 2,697,636 | no | 1 s | 5.5 GB behind (falls behind all run) |
| S1 nolanes (r11) | 2,683,629 | no | 2 s | 5.9 GB behind |
| STOCK stock (r11) | 1,398,333 | no | 1 s | 0 (in step) |
| P9 noapply (r12) | (see runs/) | no | - | about 8.9 GB behind at t1 |

- At every fixed rate 50k-1M SET/s (base args, S1 and P9, 3 reps each) there is no timeout and ACK lag <= 2 s.
- So in these runs the ACK loss appears only when the replica runs `replica-parallel-apply yes` and the stream is
  at the closed-loop rate (about 161 MB/s of replication stream, 1.3 Gb/s, far below the 9.5 Gb/s per-flow limit).
  repl-stream-sender on the primary does not change it (nosender also times out).
- With `replica-parallel-apply no` the ACKs keep flowing, but the replica cannot keep up with ~2.7M SET/s and
  falls gigabytes behind. STOCK's primary only reaches ~1.40M SET/s with stock args, and its replica keeps up.
- Primary CLIENT LIST for the replica (S1 base r11, diag-primary.txt): `tot-net-in=743` and `tot-cmds=19` at age 44
  and at age 69 (no change), `cmd=replconf`, `oll=136-137`, `omem` about 2.8 MB, `idle=0`. So during the gap the
  primary receives no bytes at all on the replica connection.
- Replica per-thread CPU (top -H, S1 base r11, diag-replica.txt): main thread about 50%, io_thd_1-4 about 55%.
  So the replica main thread is NOT at 100% in that sample; a saturated main thread does not explain it on its own.
  (Whether the replica's ACK leaves the replica is the next measurement: runs ackdiag r21/r22 add CLIENT LIST TYPE
  MASTER and ss of the replica->primary flow on the replica.)
- Data: after catch-up, primary and replica DEBUG DIGEST are equal in every run where the offsets were equal.

## Where the ACKs stop (ackdiag runs S1-max-r21, P9-max-r22, base config, 2026-10-31 02:15-02:22 UTC)
Both runs show the event again (S1: 1 timeout, ACK lag up to 58 s; P9: 2 timeouts, up to 60 s), writer 2.74M SET/s.
- Replica side (CLIENT LIST TYPE MASTER on the replica): the primary client's tot-net-out grows by about 528 B every
  12 s (one REPLCONF ACK per second, about 44 B each) during the whole gap. ss on the replica's flow to the primary:
  bytes_sent grows by the same amount and bytes_acked = bytes_sent + 1 every time. So the replica SENDS the ACKs and
  the primary host's TCP stack ACCEPTS them.
- Primary side (CLIENT LIST TYPE REPLICA on the primary, S1-max-r21): tot-net-in = 702 and tot-cmds = 18 from age 17
  to age 63 (no change), events=r, oll 136-138 reply blocks, omem about 2.8 MB. So the primary process does not read
  the bytes waiting on the replica socket.
- Compare S1-max-r11-noapply (replica-parallel-apply no, replica falls behind): the primary's replica client is
  events=rw (output backlog grows: oll 5,601 -> 162,986, omem up to 3.3 GB because the limit is off) and tot-net-in
  grows 736 -> 2,696 with tot-cmds 19 -> 64, i.e. the primary reads one ACK per second.
- Reading (a finding, not a conclusion): on S1 and P9 with lanes forced and io-threads 5, under a closed-loop SET
  stream, the primary's main loop stops reading the replica connection while that connection has only a small
  output backlog (events=r). When the backlog is large (events=rw) it keeps reading. The replica config matters only
  because it decides whether the replica keeps up (small backlog) or falls behind (large backlog). Which code path
  skips the read (staged loop polling of main-owned connections, or the read handler) is not yet located.

## Corrections to earlier reports (harness bug)
- The "WAIT 1 returned in 0.8-0.9 s" values in earlier reports mean nothing: WAIT was sent on a NEW valkey-cli
  connection, whose own write offset is 0, so WAIT returned at once. The harness now polls slave_repl_offset until it
  reaches master_repl_offset instead (catchup_*).
- The digest mismatches in the noapply and nolanes runs are the replica lag (5.5-8.9 GB behind when DEBUG DIGEST
  ran), not divergence. All 34 runs with equal offsets had equal digests.

## Not shown yet
- Why the replica's ACKs do not arrive: not sent by the replica, sent but not delivered, or delivered but not read.
- Whether the same happens at rates between 1M and 2.7M SET/s (threshold).
- Whether it happens with replication over loopback (the runner G5 cells will show the same-host case).
