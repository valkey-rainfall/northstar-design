#!/usr/bin/env python3
"""Linearizability checker for histories recorded by driver.py (standard library only).

History format: one JSON object per line:
  {"c": client_id, "i": invoke_ns, "r": complete_ns, "op": ["SET", "k", "v"], "res": <reply>}
Replies: strings, ints, null, lists, or {"err": "..."} for RESP errors.

Checks:
  (a) per-object linearizability with the Wing-Gong / Lowe (WGL) search. Objects are:
      - every single key touched by SET/GET/DEL/INCR/APPEND/GETSET/MSET/MGET/MSETNX (per-key projection:
        a multi-key command contributes one sub-operation to each key it touches, same timestamps);
      - every declared multi-key GROUP (a tuple of keys) as one object, so MSET/MGET/MSETNX/DEL-many/RENAME on
        group keys must be atomic AND real-time ordered against each other (this is the strong form of the
        snapshot check).
  (b) snapshot check for MGET versus MSET on a group: every MGET result must be all-nil or all values equal
      (the same MSET token), i.e. the state after some prefix of the MSET/DEL/MSETNX sequence.
  (c) transfer-sum invariant: every MGET over the account keys sums to the initial total.

Exit code 0 = all checks pass, 2 = a violation, 3 = usage error.
"""
import json
import sys
from collections import defaultdict

# ---------------------------------------------------------------- sequential specification

def err(res):
    return isinstance(res, dict) and "err" in res


def apply_key(state, op, res):
    """Sequential spec for one key. state: None or str. Returns new state, or False if res does not match.
    op is the per-key projection: list like ["SET", v], ["GET"], ["DEL"], ["INCR"], ["APPEND", s], ["MSETNX", v, ok]
    For projected ops the expected reply is encoded in the projection, see project()."""
    kind = op[0]
    if kind == "SET":
        if res != "OK":
            return False
        return op[1]
    if kind == "GET":
        if res != state:
            return False
        return state
    if kind == "DEL":
        want = 0 if state is None else 1
        if res != want:
            return False
        return None
    if kind == "INCR":
        cur = 0 if state is None else int(state)
        if res != cur + 1:
            return False
        return str(cur + 1)
    if kind == "APPEND":
        cur = "" if state is None else state
        new = cur + op[1]
        if res != len(new):
            return False
        return new
    if kind == "PSET":  # projected part of MSET: reply already checked at group level, value in op[1]
        return op[1]
    if kind == "PGET":  # projected part of MGET: res is the per-key element
        if res != state:
            return False
        return state
    if kind == "PDEL":  # projected part of DEL k1 k2..: reply is the count, cannot check per key; just clear
        return None
    if kind == "PSETNX":  # projected part of MSETNX: op[2] says whether the whole MSETNX succeeded
        if op[2]:
            if state is not None:
                return False  # succeeded although this key existed
            return op[1]
        return state
    raise ValueError("unknown key op %r" % (kind,))


def apply_group(state, op, res):
    """Sequential spec for a tuple-of-keys object. state: tuple of (None|str). Returns new state or False."""
    kind = op[0]
    keys = op[1]  # the group key list (fixed order)
    idx = {k: n for n, k in enumerate(keys)}
    st = list(state)
    if kind == "MSET":
        if res != "OK":
            return False
        kv = op[2]
        for k, v in kv:
            st[idx[k]] = v
        return tuple(st)
    if kind == "MGET":
        ks = op[2]
        want = [st[idx[k]] for k in ks]
        if res != want:
            return False
        return state
    if kind == "MSETNX":
        kv = op[2]
        exists = any(st[idx[k]] is not None for k, _ in kv)
        want = 0 if exists else 1
        if res != want:
            return False
        if not exists:
            for k, v in kv:
                st[idx[k]] = v
        return tuple(st)
    if kind == "DEL":
        ks = op[2]
        want = sum(1 for k in ks if st[idx[k]] is not None)
        if res != want:
            return False
        for k in ks:
            st[idx[k]] = None
        return tuple(st)
    if kind == "RENAME":
        src, dst = op[2], op[3]
        if st[idx[src]] is None:
            return state if err(res) else False
        if res != "OK":
            return False
        st[idx[dst]] = st[idx[src]]
        st[idx[src]] = None
        return tuple(st)
    if kind in ("SET", "GET", "DEL1", "INCR", "APPEND"):
        k = op[2]
        sub = [kind if kind != "DEL1" else "DEL"] + list(op[3:])
        new = apply_key(st[idx[k]], sub, res)
        if new is False:
            return False
        st[idx[k]] = new
        return tuple(st)
    raise ValueError("unknown group op %r" % (kind,))


# ---------------------------------------------------------------- WGL search

class Op:
    __slots__ = ("idx", "inv", "ret", "op", "res", "cid")

    def __init__(self, idx, inv, ret, op, res, cid):
        self.idx, self.inv, self.ret, self.op, self.res, self.cid = idx, inv, ret, op, res, cid


def wgl(ops, apply, init, max_steps=20000000):
    """Wing-Gong linearizability check with Lowe's cache of failed (linearized-set, state) configurations.
    ops: list of Op sorted by invoke time. Returns (True, None) or (False, info)."""
    n = len(ops)
    ops = sorted(ops, key=lambda o: (o.inv, o.ret))
    for k, o in enumerate(ops):
        o.idx = k
    # Remaining ops live in a doubly linked list sorted by invoke time (sentinel n = head/tail).
    nxt = list(range(1, n + 1)) + [0]
    prv = [n] + list(range(0, n)) + [0]
    prv[n] = n - 1 if n else n
    nxt[n] = 0 if n else n
    done = 0  # bitmask, part of the cache key
    state = init
    stack = []  # (done, state, candidate_list, position, removed_index)
    failed = set()
    steps = 0
    max_conc = 0

    def unlink(i):
        nxt[prv[i]] = nxt[i]
        prv[nxt[i]] = prv[i]

    def relink(i):
        nxt[prv[i]] = i
        prv[nxt[i]] = i

    def candidates():
        # Minimal elements: remaining ops invoked no later than the earliest completion among remaining ops.
        # Walking the list in invoke order with a running minimum of ret is exact: an op whose invoke is
        # later than the running minimum cannot lower it (ret >= inv), so the walk may stop there.
        # Program order inside one connection (pipelines) is kept: only the first remaining op of a client
        # is a candidate.
        cands = []
        seen = set()
        min_ret = None
        i = nxt[n]
        while i != n:
            o = ops[i]
            if min_ret is not None and o.inv > min_ret:
                break
            if min_ret is None or o.ret < min_ret:
                min_ret = o.ret
            if o.cid not in seen:
                cands.append(i)
            seen.add(o.cid)
            i = nxt[i]
        return cands

    cands = candidates()
    max_conc = max(max_conc, len(cands))
    pos = 0
    while True:
        steps += 1
        if steps > max_steps:
            return False, {"reason": "search budget exceeded", "steps": steps}
        if done == (1 << n) - 1:
            return True, {"steps": steps, "max_front": max_conc, "order": [ops[fr[4]] for fr in stack]}
        advanced = False
        while pos < len(cands):
            i = cands[pos]
            pos += 1
            o = ops[i]
            new_state = apply(state, o.op, o.res)
            if new_state is False:
                continue
            nd = done | (1 << i)
            key = (nd, new_state)
            if key in failed:
                continue
            stack.append((done, state, cands, pos, i))
            unlink(i)
            done, state = nd, new_state
            cands = candidates()
            max_conc = max(max_conc, len(cands))
            pos = 0
            advanced = True
            break
        if advanced:
            continue
        failed.add((done, state))
        if not stack:
            front = candidates()
            return False, {"reason": "no linearization", "steps": steps,
                           "state": state,
                           "front": [describe(ops[i]) for i in front[:8]]}
        done, state, cands, pos, i = stack.pop()
        relink(i)


def describe(o):
    return {"c": o.cid, "i": o.inv, "r": o.ret, "op": o.op, "res": o.res}


# ---------------------------------------------------------------- history projection

def load(path):
    hist = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                hist.append(json.loads(line))
    return hist


def project(hist, groups, skip_keys=()):
    """Returns per_key: key -> [Op], per_group: gname -> [Op]. groups: dict name -> [keys].
    Keys touched by RENAME and keys in skip_keys (accounts) are left out of the per-key check: RENAME has no
    per-key spec (the group object checks it) and account keys are changed by MULTI/EVAL transfers."""
    skip = set(skip_keys)
    for h in hist:
        if h["op"][0].upper() == "RENAME":
            skip.update(h["op"][1:3])
    key_of_group = {}
    for g, ks in groups.items():
        for k in ks:
            key_of_group[k] = g
    per_key = defaultdict(list)
    per_group = defaultdict(list)
    for n, h in enumerate(hist):
        op, res = h["op"], h["res"]
        cmd = op[0].upper()
        cid, inv, ret = h["c"], h["i"], h["r"]
        if cmd in ("SET", "GET", "DEL", "INCR", "APPEND") and len(op) <= 3 and not (cmd == "DEL" and len(op) > 2):
            k = op[1]
            if err(res):
                continue  # errors on single-key ops are not modelled (should not happen)
            per_key[k].append(Op(0, inv, ret, [cmd] + op[2:], res, cid))
            if k in key_of_group:
                g = key_of_group[k]
                kind = "DEL1" if cmd == "DEL" else cmd
                per_group[g].append(Op(0, inv, ret, [kind, groups[g], k] + op[2:], res, cid))
        elif cmd == "MSET":
            kv = [(op[i], op[i + 1]) for i in range(1, len(op), 2)]
            g = key_of_group.get(kv[0][0])
            if g is not None:
                per_group[g].append(Op(0, inv, ret, ["MSET", groups[g], kv], res, cid))
            if res == "OK":
                for k, v in kv:
                    per_key[k].append(Op(0, inv, ret, ["PSET", v], res, cid))
        elif cmd == "MSETNX":
            kv = [(op[i], op[i + 1]) for i in range(1, len(op), 2)]
            g = key_of_group.get(kv[0][0])
            if g is not None:
                per_group[g].append(Op(0, inv, ret, ["MSETNX", groups[g], kv], res, cid))
            if res in (0, 1):
                for k, v in kv:
                    per_key[k].append(Op(0, inv, ret, ["PSETNX", v, res == 1], res, cid))
        elif cmd == "MGET":
            ks = op[1:]
            g = key_of_group.get(ks[0])
            if g is not None and all(key_of_group.get(k) == g for k in ks):
                per_group[g].append(Op(0, inv, ret, ["MGET", groups[g], ks], res, cid))
            if isinstance(res, list):
                for k, v in zip(ks, res):
                    per_key[k].append(Op(0, inv, ret, ["PGET"], v, cid))
        elif cmd == "DEL":
            ks = op[1:]
            g = key_of_group.get(ks[0])
            if g is not None and all(key_of_group.get(k) == g for k in ks):
                per_group[g].append(Op(0, inv, ret, ["DEL", groups[g], ks], res, cid))
            if isinstance(res, int):
                for k in ks:
                    per_key[k].append(Op(0, inv, ret, ["PDEL"], res, cid))
        elif cmd == "RENAME":
            src, dst = op[1], op[2]
            g = key_of_group.get(src)
            if g is not None and key_of_group.get(dst) == g:
                per_group[g].append(Op(0, inv, ret, ["RENAME", groups[g], src, dst], res, cid))
        # MULTI/EXEC/EVAL transfers, WAIT, INFO etc. are not projected here.
    for k in skip:
        per_key.pop(k, None)
    return per_key, per_group


# ---------------------------------------------------------------- the three checks

def check_linearizable(per_key, per_group, groups, verbose=False):
    out = {"objects": 0, "ops": 0, "failures": [], "max_front": 0, "group_order": {}}
    for k, ops in sorted(per_key.items()):
        out["objects"] += 1
        out["ops"] += len(ops)
        ok, info = wgl(ops, apply_key, None)
        if info and "max_front" in info:
            out["max_front"] = max(out["max_front"], info["max_front"])
        if not ok:
            out["failures"].append({"object": "key:" + k, "info": info})
    for g, ops in sorted(per_group.items()):
        out["objects"] += 1
        out["ops"] += len(ops)
        init = tuple(None for _ in groups[g])
        ok, info = wgl(ops, apply_group, init)
        if info and "max_front" in info:
            out["max_front"] = max(out["max_front"], info["max_front"])
        if not ok:
            out["failures"].append({"object": "group:" + g, "info": info})
        elif info and "order" in info:
            out["group_order"][g] = info["order"]
    return out


def check_replica_prefix(hist, groups, group_order):
    """Replica reads (RMGET over a whole snapshot group) must be prefixes of the primary's write order.

    The primary's write order is only partly known from a black-box history: the WGL search returns ONE valid
    linearization, but two writes that overlap in real time may have run in either order on the server, and the
    replica applies the order the server really used. So the check uses what every linearization shares:
      - the snapshot must be uniform (never torn) and its token must come from a primary write of this group
        (MSET or successful MSETNX); all-nil needs a DEL-many or no write at all;
      - real-time order of the producing writes: if read R1 completed before read R2 was invoked, and R1 shows
        the state written by W1 and R2 the state written by W2, then W2 may not have completed before W1 was
        invoked (W2 strictly before W1 on the primary: the replica would have gone backwards);
      - a read recorded with "w": token (issued after WAIT 1 returned for the MSET that wrote token) must show a
        write that did not complete before that MSET was invoked (the acked write or a later/concurrent one);
      - the producing write must have been invoked before the read completed (no read from the future).
    A stricter position-in-the-linearization check was tried first and produced a false alarm (two concurrent
    primary MSETs applied by the replica in the other legal order), so it was replaced by this sound form.
    """
    out = {"reads": 0, "waited": 0, "nil_reads": 0, "failures": [], "writes": {}}
    key_of_group = {k: g for g, ks in groups.items() for k in ks}
    for g, order in group_order.items():
        if not g.startswith("snap"):
            continue
        keys = groups[g]
        producer = {}   # token -> Op (MSET or successful MSETNX that wrote it)
        dels = []       # DEL-many ops that cleared a non-empty group
        st = tuple(None for _ in keys)
        nwrites = 0
        for o in order:
            new = apply_group(st, o.op, o.res)
            if new is False or new == st:
                continue
            st = new
            nwrites += 1
            if o.op[0] in ("MSET", "MSETNX"):
                producer[o.op[2][0][1]] = o
            elif o.op[0] == "DEL":
                dels.append(o)
        out["writes"][g] = nwrites
        reads = []
        for h in hist:
            op = h["op"]
            if op[0] != "RMGET":
                continue
            ks = op[1:]
            if key_of_group.get(ks[0]) != g or set(ks) != set(keys) or not isinstance(h["res"], list):
                continue
            reads.append((h["i"], h["r"], h["res"], h.get("w"), h))
        reads.sort(key=lambda x: (x[0], x[1]))
        out["reads"] += len(reads)
        pending = []      # (ret, producing write) of reads not yet folded into max_inv
        max_inv = -1      # max invoke time of producing writes among reads that completed before the current inv
        for inv, ret, res, w, h in reads:
            # fold reads that completed before this one was invoked
            keep = []
            for r_, wo in pending:
                if r_ < inv:
                    if wo.inv > max_inv:
                        max_inv = wo.inv
                else:
                    keep.append((r_, wo))
            pending = keep
            vals = set(res)
            if len(vals) != 1:
                out["failures"].append({"kind": "torn", "read": h})
                continue
            tok = res[0]
            if w is not None:
                out["waited"] += 1
                if w not in producer:
                    out["failures"].append({"kind": "waited-token-not-in-primary-order", "read": h})
                    continue
            if tok is None:
                out["nil_reads"] += 1
                if w is not None:
                    # all-nil after WAIT is fine only if a DEL-many could have run after the acked MSET: a DEL
                    # that did not complete before the MSET was invoked and was invoked before this read completed
                    acked = producer[w]
                    if not any(d.ret >= acked.inv and d.inv <= ret for d in dels):
                        out["failures"].append({"kind": "stale-after-wait", "read": h, "acked": w, "seen": "nil"})
                continue  # which DEL produced an all-nil state is ambiguous; no order constraint from it
            wo = producer.get(tok)
            if wo is None:
                out["failures"].append({"kind": "unknown-token", "read": h})
                continue
            if wo.inv > ret:
                out["failures"].append({"kind": "read-from-future", "read": h, "write_inv": wo.inv})
                continue
            if wo.ret < max_inv:
                out["failures"].append({"kind": "went-backwards", "read": h, "write_ret": wo.ret,
                                        "earlier_read_write_inv": max_inv})
                continue
            if w is not None and wo.ret < producer[w].inv:
                out["failures"].append({"kind": "stale-after-wait", "read": h, "acked": w, "acked_inv": producer[w].inv,
                                        "seen_write_ret": wo.ret})
                continue
            pending.append((ret, wo))
    return out


def check_snapshot(hist, groups):
    """Every MGET over a whole snapshot group must be all-nil or all-equal (one MSET token)."""
    out = {"mgets": 0, "failures": []}
    key_of_group = {k: g for g, ks in groups.items() for k in ks}
    for h in hist:
        op = h["op"]
        if op[0].upper() not in ("MGET", "RMGET"):
            continue
        ks = op[1:]
        g = key_of_group.get(ks[0])
        if g is None or set(ks) != set(groups[g]):
            continue
        res = h["res"]
        if not isinstance(res, list):
            continue
        out["mgets"] += 1
        vals = set(res)
        if len(vals) > 1:
            out["failures"].append({"c": h["c"], "i": h["i"], "r": h["r"], "op": op[0], "keys": ks, "values": res})
    return out


def check_transfer_sum(hist, accounts, total):
    """Every MGET over the account keys must sum to total. Nil counts as 0."""
    out = {"reads": 0, "replica_reads": 0, "transfers": 0, "failures": []}
    acc = set(accounts)
    for h in hist:
        op = h["op"]
        cmd = op[0].upper()
        if cmd in ("MGET", "RMGET") and set(op[1:]) == acc:
            res = h["res"]
            if not isinstance(res, list):
                continue
            out["reads" if cmd == "MGET" else "replica_reads"] += 1
            s = sum(int(v) if v is not None else 0 for v in res)
            if s != total:
                out["failures"].append({"c": h["c"], "i": h["i"], "r": h["r"], "op": cmd, "values": res, "sum": s})
        elif cmd in ("TRANSFER", "EVALXFER"):
            if isinstance(h["res"], list):
                out["transfers"] += 1
    return out


def check_replica(hist):
    """RGET k v (a GET on the replica issued after SET k v was acknowledged and WAIT 1 returned) must return v."""
    out = {"reads": 0, "failures": []}
    for h in hist:
        if h["op"][0] == "RGET":
            out["reads"] += 1
            if h["res"] != h["op"][2]:
                out["failures"].append(h)
    return out


def check_crossslot(hist):
    """Cluster mode: every XMSET / XMGET (keys in two slots) must be rejected with a CROSSSLOT error."""
    out = {"probes": 0, "failures": []}
    for h in hist:
        if h["op"][0] in ("XMSET", "XMGET"):
            out["probes"] += 1
            if not (err(h["res"]) and "CROSSSLOT" in h["res"]["err"]):
                out["failures"].append(h)
    return out


def run_all(hist, groups, accounts=None, total=None):
    per_key, per_group = project(hist, groups, accounts or ())
    for k in list(per_key):
        if k in (accounts or ()):
            del per_key[k]
    lin = check_linearizable(per_key, per_group, groups)
    snap = check_snapshot(hist, {g: ks for g, ks in groups.items() if g.startswith("snap")})
    xfer = check_transfer_sum(hist, accounts, total) if accounts else {"reads": 0, "transfers": 0, "failures": []}
    rep = check_replica(hist)
    rpre = check_replica_prefix(hist, groups, lin.pop("group_order", {}))
    xs = check_crossslot(hist)
    ok = (not lin["failures"] and not snap["failures"] and not xfer["failures"] and not rep["failures"]
          and not rpre["failures"] and not xs["failures"])
    return ok, {"linearizable": lin, "snapshot": snap, "transfer": xfer, "replica": rep, "replica_prefix": rpre,
                "crossslot": xs}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("history")
    ap.add_argument("--meta", help="meta json written by driver.py (groups, accounts, total); default <history>.meta")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    meta_path = a.meta or a.history.rsplit(".", 1)[0] + ".meta"
    with open(meta_path) as f:
        meta = json.load(f)
    hist = load(a.history)
    ok, rep = run_all(hist, meta.get("groups", {}), meta.get("accounts"), meta.get("total"))
    rep["history_ops"] = len(hist)
    rep["ok"] = ok
    if a.json:
        print(json.dumps(rep, indent=1, default=str))
    else:
        lin, snap, xf = rep["linearizable"], rep["snapshot"], rep["transfer"]
        rp = rep["replica_prefix"]
        print("ops=%d objects=%d checked_ops=%d max_front=%d mgets=%d account_reads=%d transfers=%d "
              "replica_reads=%d replica_snap_reads=%d replica_waited_reads=%d replica_account_reads=%d "
              "primary_snap_writes=%s crossslot_probes=%d resp_errors=%d" % (
                  len(hist), lin["objects"], lin["ops"], lin["max_front"], snap["mgets"], xf["reads"],
                  xf["transfers"], rep["replica"]["reads"], rp["reads"], rp["waited"], xf["replica_reads"],
                  rp["writes"].get("snap0", 0), rep["crossslot"]["probes"], sum(1 for h in hist if err(h["res"]))))
        for f in rep["crossslot"]["failures"][:5]:
            print("CROSSSLOT-FAIL", json.dumps(f)[:600])
        for f in lin["failures"]:
            print("LIN-FAIL", json.dumps(f, default=str)[:1500])
        for f in snap["failures"][:5]:
            print("SNAP-FAIL", json.dumps(f)[:600])
        for f in xf["failures"][:5]:
            print("SUM-FAIL", json.dumps(f)[:600])
        for f in rep["replica"]["failures"][:5]:
            print("REPLICA-FAIL", json.dumps(f)[:600])
        for f in rp["failures"][:5]:
            print("RPREFIX-FAIL", json.dumps(f, default=str)[:800])
        print("VERDICT", "PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
