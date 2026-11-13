#!/usr/bin/env python3
"""Self-tests for checker.py on hand-made good and bad histories. Exit 0 if every case behaves as expected."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checker  # noqa: E402


def H(c, i, r, op, res):
    return {"c": c, "i": i, "r": r, "op": op, "res": res}


GROUPS = {"snap0": ["s0", "s1", "s2"], "pair0": ["p0", "p1"]}
ACCOUNTS = ["a0", "a1", "a2"]
TOTAL = 300

cases = []

# 1 good: sequential register history
cases.append(("good-sequential", True, [
    H(0, 0, 10, ["SET", "x", "v1"], "OK"),
    H(1, 20, 30, ["GET", "x"], "v1"),
    H(0, 40, 50, ["SET", "x", "v2"], "OK"),
    H(1, 60, 70, ["GET", "x"], "v2"),
    H(1, 80, 90, ["DEL", "x"], 1),
    H(0, 100, 110, ["GET", "x"], None),
]))

# 2 good: concurrent GET overlapping a SET may return either old or new value
cases.append(("good-concurrent-either", True, [
    H(0, 0, 10, ["SET", "x", "v1"], "OK"),
    H(0, 20, 60, ["SET", "x", "v2"], "OK"),
    H(1, 30, 40, ["GET", "x"], "v1"),
    H(2, 45, 50, ["GET", "x"], "v2"),
]))

# 3 bad: stale read. SET v2 completed at 60, GET started at 70 and returned v1 (violates G6).
cases.append(("bad-stale-read", False, [
    H(0, 0, 10, ["SET", "x", "v1"], "OK"),
    H(0, 20, 60, ["SET", "x", "v2"], "OK"),
    H(1, 70, 80, ["GET", "x"], "v1"),
]))

# 4 bad: the classic non-linearizable (but sequentially consistent per client) history:
# two concurrent writers v1, v2; client 2 reads v2 then later v1; client 3 reads v1 then later v2.
cases.append(("bad-classic-two-readers", False, [
    H(0, 0, 100, ["SET", "x", "v1"], "OK"),
    H(1, 0, 100, ["SET", "x", "v2"], "OK"),
    H(2, 10, 20, ["GET", "x"], "v2"),
    H(2, 30, 40, ["GET", "x"], "v1"),
    H(3, 10, 20, ["GET", "x"], "v1"),
    H(3, 30, 40, ["GET", "x"], "v2"),
]))

# 5 good: concurrent INCRs return distinct consecutive values in some order
cases.append(("good-incr", True, [
    H(0, 0, 50, ["INCR", "n"], 2),
    H(1, 0, 50, ["INCR", "n"], 1),
    H(2, 60, 70, ["GET", "n"], "2"),
]))

# 6 bad: lost update, two INCRs return the same value
cases.append(("bad-incr-lost-update", False, [
    H(0, 0, 50, ["INCR", "n"], 1),
    H(1, 0, 50, ["INCR", "n"], 1),
    H(2, 60, 70, ["GET", "n"], "1"),
]))

# 7 good: MSET/MGET snapshot group, reader overlapping a writer sees old or new snapshot
cases.append(("good-snapshot", True, [
    H(0, 0, 10, ["MSET", "s0", "t1", "s1", "t1", "s2", "t1"], "OK"),
    H(0, 20, 60, ["MSET", "s0", "t2", "s1", "t2", "s2", "t2"], "OK"),
    H(1, 30, 40, ["MGET", "s0", "s1", "s2"], ["t1", "t1", "t1"]),
    H(2, 35, 55, ["MGET", "s2", "s1", "s0"], ["t2", "t2", "t2"]),
    H(1, 70, 80, ["DEL", "s0", "s1", "s2"], 3),
    H(2, 90, 95, ["MGET", "s0", "s1", "s2"], [None, None, None]),
    H(0, 100, 110, ["MSETNX", "s0", "t3", "s1", "t3", "s2", "t3"], 1),
    H(1, 100, 110, ["MSETNX", "s0", "t4", "s1", "t4", "s2", "t4"], 0),
    H(2, 120, 130, ["MGET", "s0", "s1", "s2"], ["t3", "t3", "t3"]),
]))

# 8 bad: torn MGET (mixed tokens) during a concurrent MSET
cases.append(("bad-snapshot-torn", False, [
    H(0, 0, 10, ["MSET", "s0", "t1", "s1", "t1", "s2", "t1"], "OK"),
    H(0, 20, 60, ["MSET", "s0", "t2", "s1", "t2", "s2", "t2"], "OK"),
    H(1, 30, 40, ["MGET", "s0", "s1", "s2"], ["t2", "t1", "t1"]),
]))

# 9 bad: MGET snapshot is consistent per key but violates real time across the group:
# MSET t2 completed at 60, a later MGET returns the old snapshot t1.
cases.append(("bad-snapshot-stale", False, [
    H(0, 0, 10, ["MSET", "s0", "t1", "s1", "t1", "s2", "t1"], "OK"),
    H(0, 20, 60, ["MSET", "s0", "t2", "s1", "t2", "s2", "t2"], "OK"),
    H(1, 70, 80, ["MGET", "s0", "s1", "s2"], ["t1", "t1", "t1"]),
]))

# 10 bad: both MSETNX succeed on an empty group (two winners)
cases.append(("bad-msetnx-two-winners", False, [
    H(0, 0, 10, ["MSETNX", "s0", "t3", "s1", "t3", "s2", "t3"], 1),
    H(1, 0, 10, ["MSETNX", "s0", "t4", "s1", "t4", "s2", "t4"], 1),
]))

# 11 good: RENAME pair object
cases.append(("good-rename", True, [
    H(0, 0, 10, ["SET", "p0", "v1"], "OK"),
    H(0, 20, 30, ["RENAME", "p0", "p1"], "OK"),
    H(1, 40, 50, ["GET", "p0"], None),
    H(1, 60, 70, ["GET", "p1"], "v1"),
    H(1, 80, 90, ["RENAME", "p0", "p1"], {"err": "ERR no such key"}),
]))

# 12 bad: RENAME not atomic: a reader sees the value in both keys at once (per key fine, pair object not)
cases.append(("bad-rename-both-present", False, [
    H(0, 0, 10, ["SET", "p0", "v1"], "OK"),
    H(0, 20, 60, ["RENAME", "p0", "p1"], "OK"),
    H(1, 30, 40, ["GET", "p1"], "v1"),
    H(1, 45, 50, ["GET", "p0"], "v1"),
]))

# 13 good and 14 bad: transfer sum
cases.append(("good-transfer-sum", True, [
    H(0, 0, 10, ["MGET", "a0", "a1", "a2"], ["100", "100", "100"]),
    H(1, 0, 20, ["TRANSFER", "a0", "a1", "30"], ["70", "130"]),
    H(0, 30, 40, ["MGET", "a0", "a1", "a2"], ["70", "130", "100"]),
]))
cases.append(("bad-transfer-sum", False, [
    H(0, 0, 10, ["MGET", "a0", "a1", "a2"], ["100", "100", "100"]),
    H(1, 0, 20, ["TRANSFER", "a0", "a1", "30"], ["70", "130"]),
    H(0, 12, 15, ["MGET", "a0", "a1", "a2"], ["70", "100", "100"]),
]))

# 15 good: pipelined client, several ops share one invoke time, replies in order
cases.append(("good-pipelined", True, [
    H(0, 0, 10, ["SET", "x", "v1"], "OK"),
    H(0, 0, 11, ["GET", "x"], "v1"),
    H(0, 0, 12, ["APPEND", "x", "ab"], 4),
    H(0, 0, 13, ["GET", "x"], "v1ab"),
    H(1, 5, 9, ["GET", "x"], None),
]))

# 16 bad: per-connection order broken (G2): second pipelined GET returns the value from before the APPEND
cases.append(("bad-pipelined-order", False, [
    H(0, 0, 10, ["SET", "x", "v1"], "OK"),
    H(0, 0, 11, ["APPEND", "x", "ab"], 4),
    H(0, 0, 12, ["GET", "x"], "v1"),
]))


# 17 good: replica reads (RMGET) are prefixes of the primary's write order; a lagging replica may show an older
# prefix, a read after WAIT shows the acked write, and the prefix is monotone in real time.
PRIMARY = [
    H(0, 0, 10, ["MSET", "s0", "t1", "s1", "t1", "s2", "t1"], "OK"),
    H(0, 20, 30, ["MSET", "s0", "t2", "s1", "t2", "s2", "t2"], "OK"),
    H(0, 40, 50, ["DEL", "s0", "s1", "s2"], 3),
    H(0, 60, 70, ["MSET", "s0", "t3", "s1", "t3", "s2", "t3"], "OK"),
    H(0, 72, 74, ["WAIT", "1", "0"], 1),
]
cases.append(("good-replica-prefix", True, PRIMARY + [
    H(5, 32, 36, ["RMGET", "s2", "s0", "s1"], ["t1", "t1", "t1"]),   # lagging: still t1 although t2 is acked
    H(5, 44, 46, ["RMGET", "s0", "s1", "s2"], ["t2", "t2", "t2"]),
    H(6, 52, 54, ["RMGET", "s0", "s1", "s2"], [None, None, None]),  # after DEL
    dict(H(0, 76, 78, ["RMGET", "s0", "s1", "s2"], ["t3", "t3", "t3"]), w="t3"),
    H(6, 80, 82, ["RMGET", "s1", "s0", "s2"], ["t3", "t3", "t3"]),
]))

# 18 bad: torn replica snapshot (keys from two different primary writes)
cases.append(("bad-replica-torn", False, PRIMARY + [
    H(5, 32, 36, ["RMGET", "s0", "s1", "s2"], ["t2", "t1", "t1"]),
]))

# 19 bad: replica read after WAIT 1 returned for t3 still shows the older prefix t2
cases.append(("bad-replica-stale-after-wait", False, PRIMARY + [
    dict(H(0, 76, 78, ["RMGET", "s0", "s1", "s2"], ["t2", "t2", "t2"]), w="t3"),
]))

# 20 bad: replica prefix goes backwards in real time (t2 seen, then a later read sees t1 again)
cases.append(("bad-replica-prefix-backwards", False, PRIMARY + [
    H(5, 32, 36, ["RMGET", "s0", "s1", "s2"], ["t2", "t2", "t2"]),
    H(6, 38, 39, ["RMGET", "s0", "s1", "s2"], ["t1", "t1", "t1"]),
]))

# 21 bad: replica shows a write (t3, invoked at 60) before the primary even started it
cases.append(("bad-replica-read-from-future", False, PRIMARY + [
    H(5, 52, 56, ["RMGET", "s0", "s1", "s2"], ["t3", "t3", "t3"]),
]))

# 22 bad: replica account read sees half a transfer
cases.append(("bad-replica-transfer-sum", False, [
    H(0, 0, 10, ["TRANSFER", "a0", "a1", "5"], [95, 105]),
    H(5, 20, 30, ["RMGET", "a0", "a1", "a2"], ["95", "100", "100"]),
]))

def main():
    bad = 0
    for name, expect_ok, hist in cases:
        ok, rep = checker.run_all(hist, GROUPS, ACCOUNTS, TOTAL)
        status = "ok" if ok == expect_ok else "WRONG"
        if ok != expect_ok:
            bad += 1
        why = ""
        if not ok:
            f = (rep["linearizable"]["failures"] or rep["snapshot"]["failures"] or rep["transfer"]["failures"]
                 or rep["replica_prefix"]["failures"])
            why = str(f[0])[:160] if f else ""
        print("%-28s expect=%-5s got=%-5s %s %s" % (name, "PASS" if expect_ok else "FAIL", "PASS" if ok else "FAIL",
                                                     status, why))
    print("selftest:", "ALL OK" if bad == 0 else "%d WRONG" % bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
