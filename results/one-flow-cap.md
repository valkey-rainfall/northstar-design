# The one-TCP-flow limit (design doc 4.9.4)

Design doc 4.9.4 compares the replication stream with a limit of about 9.5 Gbit/s for one TCP flow
between the two instance types of section 6.1.

Setup: an earlier pair of the same instance types (server c8gn.metal-24xl, client c8gn.48xlarge), one
cluster placement group, MTU 9001, round trip 0.10 ms, ENA Express off, 2026-10-21/22.

Status of the record: the value was noted when that pair was set up, but the tool output of that
measurement was not kept, so this repository has no raw record of it. Two ways to give it a source:

- the EC2 documentation states that single-flow traffic between instances in one cluster placement group
  is limited to about 10 Gbit/s (about 5 Gbit/s outside a placement group), which matches the value; or
- measure it again on the hosts of section 6.1, for example with `iperf3 -c <server> -P 1 -t 30` (one
  flow) and `-P 8` (eight flows), and add the output here.

The replication runs (replication/RESULTS.md) stay far below the limit either way: the closed-loop SET
stream is about 161 MB/s (1.3 Gbit/s), and the ENA allowance counters did not move in any run.
