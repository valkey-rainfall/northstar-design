# P19: the S1 campaign of design doc section 6.3

Campaign P19, finished 2026-11-04, on the hosts of design doc section 6.1, boot of 2026-11-02, 120 tasks
(3 per build per cell, build order rotated per round). Only the S1 and STOCK rows are kept here; the other
rows of the campaign were intermediate test builds that the design doc does not discuss. S1 = 927094894,
STOCK = 2a23bcda0. Cells: the reference load (2,400 connections, 32 client threads, pipeline 10, 3 M keys)
with the value size and the command varied per cell; cell A is GET 16 B at io-threads 1 with 400
connections and 8 client threads. C9 and D9 force the lane path (`--io-threads-parallel-writes-min 1
--keyspace-shard-bits 8`).

### P19-S512

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 11.711 11.686 11.883 | 11.760 | 0.107 | - |

### P19-S4K

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 2.998 3.068 3.175 | 3.080 | 0.089 | - |

### P19-S64

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 17.171 17.200 17.159 | 17.177 | 0.021 | - |

### P19-B9

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 17.366 17.405 17.457 | 17.409 | 0.046 | - |

### P19-C9

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 6.114 6.116 6.122 | 6.117 | 0.004 | - |

### P19-D9

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| S1 | 3 | 8.564 8.529 8.547 | 8.547 | 0.017 | - |

### P19-A

| build | tasks | task means (M ops/s) | mean | sd | vs S1 |
|---|---:|---|---:|---:|---:|
| STOCK | 3 | 1.510 1.507 1.510 | 1.509 | 0.002 | +2.2% |
| S1 | 3 | 1.478 1.477 1.475 | 1.477 | 0.002 | - |
