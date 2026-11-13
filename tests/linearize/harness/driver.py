#!/usr/bin/env python3
"""Black-box history recorder for the linearizability check (standard library only, raw sockets).

N concurrent connections issue random operations on a small key set and record, for every operation,
the invoke time (just before the bytes are written) and the complete time (just after the reply is parsed),
in monotonic nanoseconds. The history is written as JSON lines, plus a .meta file with the key groups,
the account total and the INFO engagement counters (before/after delta), for checker.py.

Key set (all keys of a group are in distinct keyspace shards when the server has shard bits > 0):
  registers  r0..r3      SET / GET / DEL / APPEND  (single-key register-like objects)
  counters   n0, n1      INCR / GET
  snapshot   snap0 = 4 keys  MSET (one token for all) / MGET (shuffled key order) / MSETNX / DEL all
  pair       pair0 = 2 keys  SET / GET / DEL / RENAME p0 p1 / RENAME p1 p0
  accounts   a0..a3     MULTI DECRBY INCRBY EXEC transfer, EVAL transfer, MGET all (sum invariant)
  replica    rep:<cid>  SET on primary, WAIT 1 0, GET on the replica (optional, --replica-port)

Usage: driver.py --port P --seconds S --clients N [--pipeline K] [--seed X] --out hist.jsonl [--replica-port RP]
"""
import argparse
import json
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resp import Conn, RespError, encode, info, keyspace_shard  # noqa: E402

TRANSFER_LUA = ("redis.call('decrby', KEYS[1], ARGV[1]); local b = redis.call('incrby', KEYS[2], ARGV[1]); "
                "return {redis.call('get', KEYS[1]), b}")


def jsonable(x):
    if isinstance(x, bytes):
        return x.decode("latin-1")
    if isinstance(x, RespError):
        return {"err": str(x)}
    if isinstance(x, list):
        return [jsonable(y) for y in x]
    return x


def pick_keys(prefix, count, bits, taken, tag=""):
    """Pick `count` keys with the given prefix whose shards are pairwise distinct and not in `taken`.
    With a cluster hash tag every key is "{tag}prefixN" (one slot, the distinct-shard rule does not apply)."""
    out = []
    n = 0
    while len(out) < count:
        k = "%s%s%d" % (("{%s}" % tag) if tag else "", prefix, n)
        n += 1
        s = keyspace_shard(k, bits)
        if bits > 0 and not tag and s in taken:
            continue
        taken.add(s)
        out.append(k)
    return out


def crc16_xmodem(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def key_slot(key):
    """Cluster hash slot of a key (hash tag aware), copy of keyHashSlot()."""
    s = key.find("{")
    if s >= 0:
        e = key.find("}", s + 1)
        if e > s + 1:
            key = key[s + 1:e]
    return crc16_xmodem(key.encode()) & 16383


def crossslot_loop(cid, args, keys, rec, stop, rng):
    """Cluster mode: multi-key commands whose keys are in different slots must be rejected with CROSSSLOT and
    must not touch the group keys. Recorded as XMSET / XMGET (the checker requires an error reply on every one;
    a group key written by a rejected XMSET would show an unknown token to the group linearizability check)."""
    c = Conn(args.port, timeout=30.0)
    snap = keys["snap"]
    seq = 0
    other = "{%s}x" % args.cross_slot_tag
    while not stop.is_set():
        seq += 1
        tok = "x%d:%d" % (cid, seq)
        k = rng.choice(snap)
        if rng.random() < 0.5:
            timed(c, rec, cid, ["XMSET", k, tok, other, tok], "MSET", k, tok, other, tok)
        else:
            timed(c, rec, cid, ["XMGET", k, other], "MGET", k, other)
    c.close()


class Recorder:
    def __init__(self, path):
        self.f = open(path, "w")
        self.lock = threading.Lock()
        self.count = 0
        self.errors = 0

    def add(self, cid, inv, ret, op, res, waited=None):
        rec = {"c": cid, "i": inv, "r": ret, "op": op, "res": res}
        if waited is not None:
            rec["w"] = waited  # replica read issued after WAIT 1 for the primary write that produced this token
        line = json.dumps(rec)
        with self.lock:
            self.f.write(line + "\n")
            self.count += 1
            if isinstance(res, dict):
                self.errors += 1

    def close(self):
        self.f.close()


def client_loop(cid, args, keys, rec, stop, rng):
    c = Conn(args.port, timeout=30.0)
    regs, counters, snap, pair, accounts = keys["regs"], keys["counters"], keys["snap"], keys["pair"], keys["accounts"]
    seq = 0
    # operation generators: each returns (list_of_commands, record_fn) where record_fn maps replies to history ops
    while not stop.is_set():
        batch = []  # list of (op_for_history, raw_cmd_list, kind)
        n = max(1, args.pipeline)
        for _ in range(n):
            seq += 1
            r = rng.random()
            tok = "c%d:%d" % (cid, seq)
            if r < 0.30:
                k = rng.choice(regs)
                x = rng.random()
                if x < 0.35:
                    batch.append((["SET", k, tok], ["SET", k, tok]))
                elif x < 0.80:
                    batch.append((["GET", k], ["GET", k]))
                elif x < 0.90:
                    batch.append((["DEL", k], ["DEL", k]))
                else:
                    batch.append((["APPEND", k, "+"], ["APPEND", k, "+"]))
            elif r < 0.40:
                k = rng.choice(counters)
                if rng.random() < 0.6:
                    batch.append((["INCR", k], ["INCR", k]))
                else:
                    batch.append((["GET", k], ["GET", k]))
            elif r < 0.65:
                x = rng.random()
                if x < 0.35:
                    cmd = ["MSET"]
                    ks = list(snap)
                    rng.shuffle(ks)
                    for k in ks:
                        cmd += [k, tok]
                    batch.append((cmd, cmd))
                elif x < 0.90:
                    ks = list(snap)
                    rng.shuffle(ks)
                    batch.append((["MGET"] + ks, ["MGET"] + ks))
                elif x < 0.95:
                    batch.append((["DEL"] + list(snap), ["DEL"] + list(snap)))
                else:
                    cmd = ["MSETNX"]
                    for k in snap:
                        cmd += [k, tok]
                    batch.append((cmd, cmd))
            elif r < 0.80:
                x = rng.random()
                p0, p1 = pair
                if x < 0.25:
                    k = rng.choice(pair)
                    batch.append((["SET", k, tok], ["SET", k, tok]))
                elif x < 0.65:
                    k = rng.choice(pair)
                    batch.append((["GET", k], ["GET", k]))
                elif x < 0.75:
                    k = rng.choice(pair)
                    batch.append((["DEL", k], ["DEL", k]))
                elif x < 0.88:
                    batch.append((["RENAME", p0, p1], ["RENAME", p0, p1]))
                else:
                    batch.append((["RENAME", p1, p0], ["RENAME", p1, p0]))
            else:
                x = rng.random()
                if x < 0.45:
                    batch.append((["MGET"] + list(accounts), ["MGET"] + list(accounts)))
                else:
                    a, b = rng.sample(accounts, 2)
                    amt = str(rng.randint(1, 9))
                    if x < 0.75:
                        # MULTI block: 4 commands, recorded as one TRANSFER op whose result is the EXEC reply
                        batch.append((["TRANSFER", a, b, amt], [["MULTI"], ["DECRBY", a, amt], ["INCRBY", b, amt], ["EXEC"]]))
                    else:
                        batch.append((["EVALXFER", a, b, amt], ["EVAL", TRANSFER_LUA, "2", a, b, amt]))
        # send the batch in one write, read replies in order
        raw = []
        for op, cmd in batch:
            if op[0] == "TRANSFER":
                raw.extend(cmd)
            else:
                raw.append(cmd)
        payload = b"".join(encode(*x) for x in raw)
        inv = time.monotonic_ns()
        c.s.sendall(payload)
        for op, cmd in batch:
            if op[0] == "TRANSFER":
                res = [c.read() for _ in range(4)]
                ret = time.monotonic_ns()
                rec.add(cid, inv, ret, op, jsonable(res[3]))
            else:
                res = c.read()
                ret = time.monotonic_ns()
                rec.add(cid, inv, ret, op, jsonable(res))
    c.close()


def replica_loop(cid, args, rec, stop, rng):
    """SET on the primary, WAIT 1 0, then GET on the replica: the replica must already hold the value."""
    p = Conn(args.port, timeout=30.0)
    r = Conn(args.replica_port, timeout=30.0)
    k = "rep:%d" % cid
    n = 0
    while not stop.is_set():
        n += 1
        v = "c%d:%d" % (cid, n)
        inv = time.monotonic_ns()
        res = p.cmd("SET", k, v)
        ret = time.monotonic_ns()
        rec.add(cid, inv, ret, ["SET", k, v], jsonable(res))
        inv = time.monotonic_ns()
        w = p.cmd("WAIT", "1", "0")
        ret = time.monotonic_ns()
        rec.add(cid, inv, ret, ["WAIT", "1", "0"], jsonable(w))
        inv = time.monotonic_ns()
        g = r.cmd("GET", k)
        ret = time.monotonic_ns()
        rec.add(cid, inv, ret, ["RGET", k, v], jsonable(g))
    p.close()
    r.close()


def timed(c, rec, cid, op, *cmd, **kw):
    inv = time.monotonic_ns()
    res = c.cmd(*cmd)
    ret = time.monotonic_ns()
    rec.add(cid, inv, ret, op, jsonable(res), **kw)
    return res


def replica_reader_loop(cid, args, keys, rec, stop, rng):
    """Concurrent replica reader WITHOUT WAIT: MGET of the snapshot group (shuffled key order) and MGET of the
    account keys on the replica. Recorded as RMGET so the checker treats them as replica reads: every snapshot
    must be the state after some prefix of the primary's linearized write order (never torn), prefixes must be
    monotone in real time, and account sums must equal the total."""
    r = Conn(args.replica_port, timeout=30.0)
    snap, accounts = keys["snap"], keys["accounts"]
    while not stop.is_set():
        if rng.random() < 0.7:
            ks = list(snap)
            rng.shuffle(ks)
            timed(r, rec, cid, ["RMGET"] + ks, "MGET", *ks)
        else:
            timed(r, rec, cid, ["RMGET"] + list(accounts), "MGET", *accounts)
    r.close()


def replica_wait_writer_loop(cid, args, keys, rec, stop, rng):
    """Write on the primary, WAIT 1 0, then read the same group on the replica: the replica snapshot must
    include the acknowledged write (recorded with "w": token). Also MULTI transfers followed by WAIT and an
    account MGET on the replica (sum check)."""
    p = Conn(args.port, timeout=30.0)
    r = Conn(args.replica_port, timeout=30.0)
    snap, accounts = keys["snap"], keys["accounts"]
    seq = 0
    while not stop.is_set():
        seq += 1
        tok = "c%d:%d" % (cid, seq)
        if rng.random() < 0.75:
            cmd = ["MSET"]
            ks = list(snap)
            rng.shuffle(ks)
            for k in ks:
                cmd += [k, tok]
            timed(p, rec, cid, cmd, *cmd)
            w = timed(p, rec, cid, ["WAIT", "1", "0"], "WAIT", "1", "0")
            ks = list(snap)
            rng.shuffle(ks)
            timed(r, rec, cid, ["RMGET"] + ks, "MGET", *ks, waited=tok if w == 1 else None)
        else:
            a, b = rng.sample(accounts, 2)
            amt = str(rng.randint(1, 9))
            inv = time.monotonic_ns()
            p.send(["MULTI"], ["DECRBY", a, amt], ["INCRBY", b, amt], ["EXEC"])
            res = [p.read() for _ in range(4)]
            ret = time.monotonic_ns()
            rec.add(cid, inv, ret, ["TRANSFER", a, b, amt], jsonable(res[3]))
            timed(p, rec, cid, ["WAIT", "1", "0"], "WAIT", "1", "0")
            timed(r, rec, cid, ["RMGET"] + list(accounts), "MGET", *accounts)
    p.close()
    r.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--replica-port", type=int, default=0)
    ap.add_argument("--replica-readers", type=int, default=0, help="replica MGET readers without WAIT (needs --replica-port)")
    ap.add_argument("--replica-wait-writers", type=int, default=0, help="primary write, WAIT 1, replica MGET (needs --replica-port)")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--clients", type=int, default=8)
    ap.add_argument("--pipeline", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hashtag", default="", help="cluster mode: put every key in slot of {hashtag}")
    ap.add_argument("--cross-slot-tag", default="", help="cluster mode: tag of a different slot for CROSSSLOT probes")
    ap.add_argument("--cross-slot-clients", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    d = info(a.port)
    bits = int(d.get("keyspace_shard_bits", "0"))
    taken = set()
    keys = {
        "regs": pick_keys("r", 4, bits, taken, a.hashtag),
        "counters": pick_keys("n", 2, bits, taken, a.hashtag),
        "snap": pick_keys("snap", 4, bits, taken, a.hashtag),
        "pair": pick_keys("p", 2, bits, taken, a.hashtag),
        "accounts": pick_keys("a", 4, bits, taken, a.hashtag),
    }
    total = 100 * len(keys["accounts"])
    c = Conn(a.port)
    c.cmd("FLUSHALL")
    mset = ["MSET"]
    for k in keys["accounts"]:
        mset += [k, "100"]
    assert c.cmd(*mset) == b"OK"
    if a.replica_port:
        assert c.cmd("WAIT", "1", "5000") == 1, "replica not attached"
    c.close()
    before = info(a.port)
    rec = Recorder(a.out)
    stop = threading.Event()
    threads = []
    for cid in range(a.clients):
        t = threading.Thread(target=client_loop, args=(cid, a, keys, rec, stop, random.Random(rng.random())))
        t.start()
        threads.append(t)
    if a.replica_port:
        t = threading.Thread(target=replica_loop, args=(1000, a, rec, stop, random.Random(rng.random())))
        t.start()
        threads.append(t)
        for n in range(a.replica_readers):
            t = threading.Thread(target=replica_reader_loop, args=(2000 + n, a, keys, rec, stop, random.Random(rng.random())))
            t.start()
            threads.append(t)
        for n in range(a.replica_wait_writers):
            t = threading.Thread(target=replica_wait_writer_loop, args=(3000 + n, a, keys, rec, stop, random.Random(rng.random())))
            t.start()
            threads.append(t)
    for n in range(a.cross_slot_clients):
        t = threading.Thread(target=crossslot_loop, args=(4000 + n, a, keys, rec, stop, random.Random(rng.random())))
        t.start()
        threads.append(t)
    rbefore = info(a.replica_port) if a.replica_port else {}
    time.sleep(a.seconds)
    stop.set()
    for t in threads:
        t.join()
    rec.close()
    after = info(a.port)
    rafter = info(a.replica_port) if a.replica_port else {}
    fields = ["fastpath_clients", "fastpath_reads", "fastpath_writes", "fastpath_batches", "fastpath_speculated",
              "fastpath_write_lane_phases", "fastpath_write_lane_entries", "fastpath_write_barriers",
              "fastpath_write_serial_segments", "total_commands_processed", "io_threads_active",
              "keyspace_shard_bits", "staged_stream_phases", "staged_check_stream_execs",
              "staged_check_stream_multi", "staged_check_stream_runs", "staged_check_stream_entries",
              "staged_check_stream_cuts"]
    eng = {}
    for f in fields:
        try:
            eng[f] = int(after.get(f, 0)) - int(before.get(f, 0))
        except ValueError:
            eng[f] = after.get(f)
    eng["fastpath_clients_after"] = after.get("fastpath_clients")
    eng["keyspace_shard_bits"] = bits
    reng = {}
    if a.replica_port:
        for f in ["repl_parallel_applied", "repl_apply_phases", "repl_lane_barriers", "repl_lane_rechecks",
                  "repl_lane_demoted", "repl_lane_reads", "staged_apply_phases", "total_commands_processed",
                  "fastpath_reads", "fastpath_clients"]:
            try:
                reng[f] = int(rafter.get(f, 0)) - int(rbefore.get(f, 0))
            except ValueError:
                reng[f] = rafter.get(f)
        reng["master_link_status"] = rafter.get("master_link_status")
        reng["role"] = rafter.get("role")
    meta = {"groups": {"snap0": keys["snap"], "pair0": keys["pair"]}, "accounts": keys["accounts"], "total": total,
            "keys": keys, "engagement": eng, "replica_engagement": reng, "ops": rec.count, "resp_errors": rec.errors,
            "config": vars(a), "shards": {k: keyspace_shard(k, bits) for g in keys.values() for k in g},
            "slots": {k: key_slot(k) for g in keys.values() for k in g},
            "cluster": {f: after.get(f) for f in ("cluster_enabled",)}}
    with open(a.out.rsplit(".", 1)[0] + ".meta", "w") as f:
        json.dump(meta, f, indent=1)
    print("ops=%d errors=%d engagement=%s replica=%s" % (rec.count, rec.errors, json.dumps(eng), json.dumps(reng)))


if __name__ == "__main__":
    main()
