# REPRODUCE: W-C2 linearize

All commands are bash. `$S` is a scratch directory of your choice. `$A` is the root of this
repository. Nothing here needs network access except the clone in step 1.

## 1. Get the code (full SHA 1fb18b7d25e043f1a94794eeb9957d75a7becf9f)

    S=/path/to/scratch; A=/path/to/this/repository
    git clone --filter=blob:none https://github.com/valkey-rainfall/valkey.git $S/valkey
    git -C $S/valkey worktree add --detach $S/wt-head 1fb18b7d25e043f1a94794eeb9957d75a7becf9f
    (cd $S/wt-head && make -j4)          # gcc 11.5 was used; valkey-server and valkey-cli land in src/

## 2. Check the checker on hand-made histories (expected: "selftest: ALL OK", 16 cases)

    python3 $A/tests/linearize/harness/selftest.py

## 3. One history by hand (expected: VERDICT PASS, lane counters > 0)

    export WORK=$S            # server.sh and run_matrix.sh put run dirs under $WORK/run-linearize
    export VK_SRC=$S/wt-head/src
    $A/tests/linearize/harness/server.sh start 38510 lanes      # io-threads 5, io-threads-parallel-writes-min 1
    python3 $A/tests/linearize/harness/driver.py --port 38510 --seconds 10 --clients 8 --pipeline 4 --seed 1 --out $S/h1.jsonl
    python3 $A/tests/linearize/harness/checker.py $S/h1.jsonl   # reads $S/h1.meta written by the driver
    $A/tests/linearize/harness/server.sh stop 38510

The driver prints the INFO engagement delta (fastpath_write_lane_entries, fastpath_write_lane_phases,
fastpath_write_barriers, fastpath_reads, fastpath_writes, fastpath_speculated). With `lanes` all of them except
speculated must be large; with `baseline` all are 0.

## 4. The matrices (expected: every line PASS; lanes lines have lane_entries > 0)

    $A/tests/linearize/harness/run_matrix.sh lanes    38510 30 10 lanes        # 30 histories x 10 s, odd = not pipelined, even = pipelined 4
    $A/tests/linearize/harness/run_matrix.sh baseline 38520 30 10 baseline     # io-threads 1, fast path off
    # primary + replica (replica started first so that it attaches as soon as the primary is up):
    $A/tests/linearize/harness/server.sh start 38531 lanes --replicaof 127.0.0.1 38530
    $A/tests/linearize/harness/server.sh start 38530 lanes
    REPLICA_PORT=38531 $A/tests/linearize/harness/run_matrix.sh lanes 38530 6 10 lanes-replica
    $A/tests/linearize/harness/server.sh stop 38531

Summaries land in $WORK/run-linearize/<tag>/summary.txt (copied to tests/linearize/results/).
A failing history is kept as hNN.jsonl next to its .meta and .check; passing histories are deleted (size).

## 5. The mutant (expected: VERDICT FAIL with LIN-FAIL lines on pipelined histories; PASS without pipelining)

    git -C $S/valkey worktree add --detach $S/wt-mut 1fb18b7d25e043f1a94794eeb9957d75a7becf9f
    (cd $S/wt-mut && git apply $A/tests/linearize/mutation-reverse-lane-order.patch && make -j4)
    VK_SRC=$S/wt-mut/src $A/tests/linearize/harness/server.sh start 38540 lanes
    python3 $A/tests/linearize/harness/driver.py --port 38540 --seconds 5 --clients 8 --pipeline 4 --seed 1 --out $S/m1.jsonl
    python3 $A/tests/linearize/harness/checker.py $S/m1.jsonl     # FAIL
    python3 $A/tests/linearize/harness/driver.py --port 38540 --seconds 5 --clients 8 --pipeline 0 --seed 3 --out $S/m3.jsonl
    python3 $A/tests/linearize/harness/checker.py $S/m3.jsonl     # PASS (see README: the mutation is only visible through program order)
    VK_SRC=$S/wt-mut/src $A/tests/linearize/harness/server.sh stop 38540

## 6. Re-check a preserved history without any server

The checker reads `<name>.meta` next to `<name>.jsonl`, so unpack the history under the same base name as its meta:

    R=$A/tests/linearize/results
    gunzip -c $R/mutant-pipelined-seed1-FAIL.jsonl.gz > $S/mutant-pipelined-seed1-FAIL.jsonl
    cp $R/mutant-pipelined-seed1-FAIL.meta $S/
    python3 $A/tests/linearize/harness/checker.py $S/mutant-pipelined-seed1-FAIL.jsonl    # VERDICT FAIL
    (same for the lanes-*/baseline-* files: VERDICT PASS)
