# results

Throughput and latency measurements behind section 6 (and parts of 4.9 and 7) of the design document.

| File | Campaign | Content |
|---|---|---|
| p19-s1-campaign.md | P19, 2026-11-04 | S1 and STOCK on the reference load with other value sizes, SET, mixed, io-threads 1 |
| p21.md | P21, 2026-11-05 to 11-09 | Reference load (STOCK, C, collector thread), bisect, shard diagnostic, generator calibration, Figure 1 sweep, AOF cell, A/B check |
| p21/ | P21 | A/B per-task values, AOF per-rep table, the note on the failed AOF rep |
| p22.md, p22/ | P22, 2026-11-09 to 11-10 | SET sweep (Figure 2), the io-threads 10 matrix, io-threads 11 check |
| p23.md, p23/ | P23, 2026-11-11 | The seqlock design against C, pipeline 64 and 16, mixed loads, fixed-rate latency |
| ena/ena-per-task.tsv | P11 to P21, 2026-10-30 to 11-06 | ENA allowance-exceeded counter deltas per task, 578 tasks (client, server): bw_in, bw_out, pps, conntrack, linklocal |
| ena/{server,client}-phase22.txt, -phase23.txt | P22, P23 | Raw samples every 2 s: epoch seconds, then the same five counters |
| replication/ | 2026-10-31 | Cross-host replication runs (primary, replica and writer on three hosts) |
| one-flow-cap.md | - | The one-TCP-flow limit used in design doc 4.9.4 |

## Hosts

Two EC2 hosts in one cluster placement group, MTU 9001, round trip about 0.10 ms:

| Host | Instance type | vCPUs | NIC | Role |
|---|---|---:|---|---|
| server | c8gn.metal-24xl (Graviton 4) | 96 | 300 Gbps | the server under test |
| client | c8gn.48xlarge (Graviton 4) | 192 | 600 Gbps | the load generator |

Linux 6.18.35 (Amazon Linux 2023, aarch64) before the reboot of 2026-11-07, 6.18.56 after it. Results
from different boots are compared only through an anchor build in the same cell (see p21.md "Post-reboot
S1 check"). The replication runs used a third host of the server type as the replica.

## One task

A task is one run of one build on one cell: 10 s warmup, then 5 repetitions of 30 s (the generator
calibration and some checks use 2). Before each repetition the runner restarts the server, drops the page cache and stops
irqbalance on the server host. The server command line, with N = io-threads:

    valkey-server --port 6379 --save "" --protected-mode no --daemonize yes --io-threads N \
        --server-cpulist 0,...,N --bio-cpulist ... <cell server args>

The main thread and the IO threads are pinned to CPUs 0 to N, the NIC interrupts to CPUs 64-95. Cell
server args are named in each result file (for example `--io-threads-epoll-thread yes` for the collector
thread, `--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8` for "lanes forced").

The generator is cachecannon. Example: the configuration of one of the two client processes of a
Figure 1 task (GET 16 B, pipeline 64, 2,400 connections in total, io-threads 62); the other process
uses `cpu_list = "16-103"`:

    [general]
    duration = "30s"
    warmup = "10s"
    threads = 88
    cpu_list = "104-191"
    io_engine = "uring"

    [target]
    endpoints = ["198.51.100.10:6379"]
    protocol = "resp"

    [connection]
    connections = 1200
    pipeline_depth = 64

    [workload]
    prefill = true

    [workload.keyspace]
    length = 16
    count = 3000000
    distribution = "uniform"

    [workload.commands]
    get = 100
    set = 0
    delete = 0

    [workload.values]
    length = 16

    [timestamps]
    enabled = true
    mode = "userspace"

    [admin]
    format = "json"

A SET cell sets `get = 0` and `set = 100`; the P23d mixed cells set `set = 20` or `set = 50`; a
fixed-rate task adds a total rate split evenly over the processes. The address is a documentation
placeholder.

A cell result is the mean of the task means, with the standard deviation (sd) of the task means. A task
fails, and is listed as failed, if the generator reports any error.
