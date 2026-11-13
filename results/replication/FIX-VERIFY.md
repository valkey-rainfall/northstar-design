# Phase 13 fix verification on the test hosts (2026-10-31 03:39-03:46 UTC) - a finding for this exact config

Build FIX: valkey-rainfall/valkey commit f65f429effe1156eb1942da57856d829213f9a26 (parent e82fc7da), cloned to
~/xh/FIX-src on server-host, `cd src && MAKEFLAGS= make -j48`, rc=0, binary sha256 079b8571... (same file on server
and replica, `valkey-server --version` sha=f65f429e:0). Built only after the runner task on the test hosts had finished.

Config (same as the failing base runs): primary `--io-threads 5 --io-threads-parallel-writes-min 1
--keyspace-shard-bits 8 --repl-stream-sender yes`, default diskless sync (so the sender does not own the replica:
repl_sender_replicas 0 in every sample), replica `--replica-parallel-apply yes`, both `--save '' --appendonly no
--client-output-buffer-limit 'replica 0 0 0' --repl-backlog-size 1gb`, repl-timeout 60. Writer cachecannon e545c26,
2400 conns, 32 threads, P10, SET 100%, 16 B, closed loop 60 s.

| run | SET/s | timeouts | max ACK lag | primary's replica client tot-net-in / tot-cmds (first -> last diag sample) | catch-up | digests |
|---|---:|---:|---:|---|---|---|
| FIX-max-r51 | 2,745,785 | 0 | 1 s | 590 / 15 -> 3,822 / 89 | 0.8 s | equal |
| FIX-max-r52 | 2,743,018 | 0 | 1 s | 625 / 16 -> 3,896 / 91 | 0.9 s | equal |

Before the fix, same config (S1/P9/PROBE base runs r1-r3, r11, r21, r22, r31): 1-4 timeouts per run, ACK lag
58-61 s, tot-net-in frozen for 40-80 s. After: the primary reads about one ACK per second for the whole run.
Writer throughput is the same as before the fix (2.73-2.75M SET/s).
STOCK reference with diagnostics already exists (STOCK-max-r11-stock, STOCK-max-r12-stock: 1.40M SET/s, 0 timeouts).

## Open item: is a PSYNC-resumed replica sender-eligible? (from source at e82fc7da, not tested separately)
- The sender takes a replica only in replStreamSenderAdd(), called from replicaPutOnline() (replication.c:2028) and
  from replStreamSenderAdoptOnline() when the sender thread starts (repl_sender.c:496). The account pass only removes
  replicas (repl_sender.c:328 comment: "New replicas join only through replStreamSenderAdd").
- primaryTryPartialResynchronization() (replication.c:1202) sets repl_state = REPLICA_STATE_ONLINE directly
  (about line 1275) and does not call replicaPutOnline() or replStreamSenderAdd().
- So a replica that comes back through PSYNC stays on the main path until the sender thread is restarted (config
  change off/on) - matching PROBE-max-r31, where repl_sender_replicas stayed 0 after the partial resync with the
  sender enabled. Eligibility itself (replStreamSenderEligible) would pass for it; it is just never offered.
