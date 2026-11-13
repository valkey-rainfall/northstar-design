# Phase 13 probe result (the test hosts, 2026-10-31 03:04-03:08 UTC) - a finding, not a conclusion

Run: runs/PROBE-max-r31 (primary.log, diag-primary.txt, samples.txt, writer.out, run.json).
Binary PROBE: valkey-rainfall/valkey commit e82fc7da plus a diagnostic counter patch (not published; sha256 3de17c68...),
built on server-host with `cd src && MAKEFLAGS= make -j48`; binary sha256 0b360a1a..., same file on server and replica.
Config: S1-base closed loop. Primary `--io-threads 5 --io-threads-parallel-writes-min 1 --keyspace-shard-bits 8
--repl-stream-sender yes` (default repl-diskless-sync yes, so repl_sender_replicas = 0: the sender did NOT own the
replica); replica `--replica-parallel-apply yes`; both `--save '' --appendonly no --client-output-buffer-limit
'replica 0 0 0' --repl-backlog-size 1gb`, repl-timeout 60. Writer cachecannon e545c26, 2400 conns, 32 threads, P10,
SET 100%, 16 B, closed loop 60 s: 2,734,495 SET/s.

## Primary log, PROBE line every 5 s (cumulative counters)
| time UTC | ae_checked | ae_fired | replica_ack_reads | note |
|---|---:|---:|---:|---|
| 03:04:54 | 343 | 17 | 8 | prefill |
| 03:04:59 | 1,088 | 277 | 13 | stream starts |
| 03:05:04 | 1,697 | 791 | 14 | |
| 03:05:30 | 4,701 | 3,387 | 14 | |
| 03:05:56 | 7,705 | 5,996 | 14 | |
| 03:06:00 | - | - | - | "Disconnecting timedout replica", partial resync |
| 03:06:27 | 11,318 | 9,094 | 14 | |
| 03:06:32 | 11,921 | 9,545 | 42 | 28 ACKs read in one burst |
| 03:07:03 | 15,533 | 12,689 | 42 | |
| 03:07:08 | 15,766 | 12,823 | 81 | writer stops: reads resume |

- From 03:05:04 to 03:06:27 (83 s) ae_fired climbs by about 520 per 5 s (about 104 aeProcessEvents per second in
  the staged write phase), while replica_ack_reads stays at 14.
- diag-primary.txt (every ~4 s, INFO and CLIENT LIST TYPE REPLICA on the primary) agrees: probe_ae_fired 300 -> 6,208
  while probe_replica_ack_reads stays 14 and the replica client's tot-net-in = 737, tot-cmds = 19 from age 18 to age
  77; the client shows events=rw for the first ~12 s and events=r after that; oll 135-138, omem about 2.8 MB.
- So: ae_fired CLIMBS while the replica ACK reads are FLAT = H2 as defined in the probe (the event loop runs, but the
  replica fd's read is not dispatched / not processed while the stream is being written by main).

## Related, from the sender-true controls (same rig, same day)
repl-stream-sender only owns a replica that did not get a diskless (socket) RDB: replication.c:2497 sets
stream_ineligible = 1 at the diskless RDB -> stream handoff, replStreamSenderEligible() refuses it. With
`--repl-diskless-sync no` on the primary the sender owns the replica (repl_sender_replicas = 1 at t0 and in every
sample). Closed loop, 1 run each:
| run | primary sync | sender owns replica | SET/s | timeouts | max ACK lag |
|---|---|---|---:|---:|---:|
| S1-max-r41-sender | disk | yes (1) | 2,776,649 | 0 | 1 s |
| S1-max-r41-nosender2 | disk | no (0, sender off) | 2,747,741 | 1 | 61 s |
| P9-max-r42-sender | disk | yes (1) | 2,779,660 | 0 | 1 s |
| P9-max-r42-nosender2 | disk | no (0) | 2,728,874 | 2 | 61 s |
When the sender thread writes the stream (main does not write it), the primary reads every ACK. When main writes the
stream, the ACK reads stop. Note: after the partial resync in PROBE-max-r31 (diskless initial sync, sender enabled)
repl_sender_replicas stayed 0 in the remaining samples; whether a PSYNC'd replica is eligible was not checked further.
PROBE-max-r33-sender (PROBE binary, `--repl-diskless-sync no`, sender on): 2,768,084 SET/s, repl_sender_replicas 1 in
all 19 samples, 0 timeouts, max ACK lag 1 s; replica_ack_reads climbs about 1 per second (12 -> 43 -> 73 over the
log lines 30 s apart) while ae_fired grows only about 5-15 per second (134 -> 344 -> 418), far fewer than in r31.
