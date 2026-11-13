# P21-AOF9 S1 R2 failure (2026-11-09)

Task 2026.11.09_15.39.51.431693 (P21-AOF9-R2, S1 927094894, the runner).

- Rep 1/5: 1952849 rps, 0.00% errors.
- Rep 2/5 (17:59:59 - 18:01:44 UTC): errors 24000 = timeouts 24000,
  err_pct 0.0435%, threshold 0%, so the task failed. throughput 1838364,
  set p999 595591 us, max 754974 us, conns_active 959 of 2400,
  conns_failed 0. Last 1 s sample: 871416 req/s.
- 24000 = 2400 conns x pipeline 10: one full pipeline per connection timed out.
- Server log for the rep window: 18 automatic AOF rewrites (normal for
  these reps), no warning lines, no "fsync is taking too long".
- The rep's AOF dir (p21aof-S1-R2-1794238790132) was already deleted by
  the runner before this was checked.
- Cause not determined. No retry was done.

Files:
- runner-log-S1-R2.txt: client runner log from the task start (400 lines).
- server-log-1759-1802.txt, server-log-rep2-window.txt: valkey-server.log
  lines on server-host.

Action: the queued P21-PROC2CHK-io62 task 2026.11.09_15.54.41.571054 was
cancelled at 18:16:31 UTC. The running task (P21-AOF9-R3 PRE-C) was left to
finish.
