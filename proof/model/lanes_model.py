#!/usr/bin/env python3
"""Exhaustive-interleaving model of the proof-of-concept write-lane plan (standard library only).

The model follows src/fastpath.c at HEAD (origin/audit/issue29-counter-recheck):
  - an iteration = READ phase (fast GET for clients with nothing in flight, harvest, classify),
    then the write step (fpExecuteWithLanes: thread-major T order, lane segments between barriers),
    then REPLY.
  - lane entries are sequences of per-key steps; a lane phase explores ALL interleavings of the
    lanes' step sequences (each lane keeps its own order).
  - the checker builds the design's claimed linearization S (fast GETs of the iteration, then T
    order) and replays it on a serial reference machine; every reply and the final state must match.
    G1/G2 (reply order, client order) and G6 (real time) hold by construction of S and are asserted.

Run:  python3 lanes_model.py            (correct design + every broken variant, fixed seeds)
      python3 lanes_model.py --seeds 60 (more random scenarios)
"""
import itertools
import random
import sys

# ----------------------------------------------------------------------------- reference machine


class Ref:
    """Serial reference: commands run one at a time, whole."""

    def __init__(self):
        self.kv = {}
        self.watch = {}  # client -> {key: dirty}

    def write(self, k):
        for w in self.watch.values():
            if k in w:
                w[k] = True

    def run(self, cl, cmd):
        op = cmd[0]
        if op == "SET":
            self.kv[cmd[1]] = cmd[2]
            self.write(cmd[1])
            return "OK"
        if op == "GET":
            return self.kv.get(cmd[1])
        if op == "INCR":
            cur = self.kv.get(cmd[1])
            if cur is not None and not cur.isdigit():
                return "ERR"
            v = int(cur or 0) + 1
            self.kv[cmd[1]] = str(v)
            self.write(cmd[1])
            return v
        if op == "DEL":
            n = 0
            for k in cmd[1:]:
                if k in self.kv:
                    del self.kv[k]
                    n += 1
                    self.write(k)
            return n
        if op == "MSET":
            for i in range(1, len(cmd), 2):
                self.kv[cmd[i]] = cmd[i + 1]
                self.write(cmd[i])
            return "OK"
        if op == "MGET":
            return tuple(self.kv.get(k) for k in cmd[1:])
        if op == "RENAME":
            a, b = cmd[1], cmd[2]
            if a not in self.kv:
                return "ERR"
            self.kv[b] = self.kv.pop(a)
            self.write(a)
            self.write(b)
            return "OK"
        if op == "WATCH":
            self.watch.setdefault(cl, {})[cmd[1]] = False
            return "OK"
        if op == "EXEC":
            w = self.watch.pop(cl, {})
            if any(w.values()):
                return "ABORT"
            return tuple(self.run(cl, c) for c in cmd[1])
        raise ValueError(op)


# ----------------------------------------------------------------------------- the lane design


class Design:
    """One execution of the lane plan under a set of choices. Flags switch on broken variants."""

    def __init__(self, shard_of, nlanes, flags=()):
        self.shard_of = shard_of
        self.nlanes = nlanes
        self.flags = set(flags)
        self.kv = {}
        self.watch = {}  # client -> {key: dirty}; lanes never touch it (as in the C code)
        self.replies = {}  # client -> list of replies in delivery order
        self.lin = []  # the claimed linearization: (client, cmd)
        self.exec_count = 0

    # --- classification (fpLaneOf / fpKeysShard / fpTrySplit / fpClassify)
    def keys(self, cmd):
        op = cmd[0]
        if op in ("SET", "GET", "INCR"):
            return [cmd[1]]
        if op == "DEL" or op == "MGET":
            return list(cmd[1:])
        if op == "MSET":
            return [cmd[i] for i in range(1, len(cmd), 2)]
        if op == "RENAME":
            return [cmd[1], cmd[2]]
        return None  # WATCH, EXEC: main only (not in fp_lane_commands)

    def lane_of(self, k):
        return self.shard_of[k] % self.nlanes

    def classify(self, cmd, observed):
        """Returns ('lane', lane) | ('split', {lane: [keys]}) | ('barrier',)."""
        ks = self.keys(cmd)
        if ks is None:
            return ("barrier",)
        if any(k in observed for k in ks):
            return ("barrier",)
        lanes = {self.lane_of(k) for k in ks}
        if len(lanes) == 1:
            return ("lane", lanes.pop())
        if "no_barrier_for_cross_lane" in self.flags:
            return ("lane", self.lane_of(ks[0]))  # BROKEN: run a cross-lane command on one lane
        if cmd[0] in ("MSET", "MGET"):
            parts = {}
            for k in ks:
                parts.setdefault(self.lane_of(k), []).append(k)
            return ("split", parts)
        return ("barrier",)

    # --- steps a lane entry performs (per-key granularity)
    def steps(self, cmd, keys=None):
        op = cmd[0]
        if op == "SET":
            return [("w", cmd[1], cmd[2])]
        if op == "GET":
            return [("r", cmd[1])]
        if op == "INCR":
            return [("incr", cmd[1])]
        if op == "DEL":
            return [("d", k) for k in cmd[1:]]
        if op == "MSET":
            vals = dict(zip(cmd[1::2], cmd[2::2]))
            return [("w", k, vals[k]) for k in (keys or cmd[1::2])]
        if op == "MGET":
            return [("r", k) for k in (keys or cmd[1:])]
        if op == "RENAME":
            return [("rn_r", cmd[1]), ("rn_w", cmd[2]), ("rn_d", cmd[1])]
        raise ValueError(op)

    def do_step(self, st, entry):
        """entry: dict with 'out' list collecting step results."""
        kind = st[0]
        if kind == "w":
            self.kv[st[1]] = st[2]
        elif kind == "r":
            entry["out"].append(self.kv.get(st[1]))
        elif kind == "incr":
            cur = self.kv.get(st[1])
            if cur is not None and not cur.isdigit():
                entry["out"].append("ERR")
            else:
                v = int(cur or 0) + 1
                self.kv[st[1]] = str(v)
                entry["out"].append(v)
        elif kind == "d":
            if st[1] in self.kv:
                del self.kv[st[1]]
                entry["out"].append(1)
        elif kind == "rn_r":
            entry["tmp"] = self.kv.get(st[1], "__missing__")
        elif kind == "rn_w":
            if entry["tmp"] != "__missing__":
                self.kv[st[1]] = entry["tmp"]
        elif kind == "rn_d":
            if entry["tmp"] != "__missing__":
                self.kv.pop(st[1], None)
                entry["out"].append("OK")
            else:
                entry["out"].append("ERR")

    def entry_reply(self, e):
        op = e["cmd"][0]
        if op in ("SET", "MSET"):
            return "OK"
        if op == "GET":
            return e["out"][0]
        if op == "INCR":
            return e["out"][0]
        if op == "DEL":
            return len(e["out"])
        if op == "MGET":
            return tuple(e["out"])
        if op == "RENAME":
            return e["out"][0]
        raise ValueError(op)

    # --- main-thread execution (barriers, serial segments): whole command, marks watchers dirty
    def main_exec(self, cl, cmd):
        ref = Ref()
        ref.kv = self.kv
        ref.watch = self.watch
        r = ref.run(cl, cmd)
        self.kv = ref.kv
        self.watch = ref.watch
        self.exec_count += 1
        return r


def interleavings(seqs, cap):
    """All merges of the sequences (each keeps its order). seqs: list of lists of items."""
    n = len(seqs)
    lens = [len(s) for s in seqs]
    total = sum(lens)
    if total == 0:
        yield []
        return
    # count merges; sample when above cap
    count = 1
    rem = total
    for l in lens:
        count *= _comb(rem, l)
        rem -= l
    if count <= cap:
        for order in _merge_orders(lens):
            idx = [0] * n
            out = []
            for lane in order:
                out.append(seqs[lane][idx[lane]])
                idx[lane] += 1
            yield out
    else:
        rng = random.Random(count)
        for _ in range(cap):
            idx = [0] * n
            out = []
            while len(out) < total:
                choices = [i for i in range(n) if idx[i] < lens[i]]
                lane = rng.choice(choices)
                out.append(seqs[lane][idx[lane]])
                idx[lane] += 1
            yield out


def _comb(n, k):
    from math import comb
    return comb(n, k)


def _merge_orders(lens):
    if sum(lens) == 0:
        yield []
        return
    for i, l in enumerate(lens):
        if l:
            lens2 = list(lens)
            lens2[i] -= 1
            for rest in _merge_orders(lens2):
                yield [i] + rest


# ----------------------------------------------------------------------------- one scenario


class Scenario:
    def __init__(self, keys, nshards, nlanes, programs, thread_of, arrivals, harvest_orders, flags=()):
        self.keys = keys
        self.shard_of = {k: i % nshards for i, k in enumerate(keys)}
        self.nlanes = nlanes
        self.programs = programs  # client -> list of cmds
        self.thread_of = thread_of  # client -> tid
        self.arrivals = arrivals  # list per iteration of {client: count of new commands}
        self.harvest_orders = harvest_orders  # per iteration: {tid: [clients in fd-claim order]}
        self.flags = set(flags)

    def executions(self, cap_per_phase=400, cap_total=3000):
        """Yield (design, lin) for each explored execution."""
        nthreads = max(self.thread_of.values()) + 1
        count = [0]

        def rec_iterations(d, it, pos, inflight_replies):
            if count[0] >= cap_total:
                return
            if it == len(self.arrivals):
                count[0] += 1
                yield d
                return
            # ---- READ phase: fast GET then harvest/classify
            observed = set()
            for cl, w in d.watch.items():
                observed |= set(w.keys())
            newpos = dict(pos)
            slot_counter = [0]
            threads = [[] for _ in range(nthreads)]  # tid -> list of (client, cmd)
            for tid in range(nthreads):
                for cl in self.harvest_orders[it].get(tid, []):
                    n = self.arrivals[it].get(cl, 0)
                    cmds = self.programs[cl][pos[cl]:pos[cl] + n]
                    newpos[cl] = pos[cl] + n
                    # fast GET: leading GETs when nothing is in flight for this client
                    nothing_inflight = True  # replies of iteration it-1 all went out in its REPLY phase
                    i = 0
                    if "fast_get_ignores_inflight" in self.flags:
                        # BROKEN: speculate even when earlier commands of this client are in the batch
                        pass
                    while i < len(cmds) and cmds[i][0] == "GET" and (nothing_inflight or "fast_get_ignores_inflight" in self.flags):
                        if "fast_get_ignores_inflight" in self.flags and i > 0:
                            # the earlier commands sit in the batch; the GET is answered now
                            pass
                        d.replies.setdefault(cl, []).append(d.kv.get(cmds[i][1]))
                        d.lin.append((cl, cmds[i]))
                        i += 1
                        if "fast_get_ignores_inflight" not in self.flags:
                            pass
                    if "fast_get_ignores_inflight" in self.flags:
                        # answer every GET of the client now, leave the rest in order (reply order broken)
                        rest = []
                        for c in cmds[i:]:
                            if c[0] == "GET":
                                d.replies.setdefault(cl, []).append(d.kv.get(c[1]))
                                d.lin.append((cl, c))
                            else:
                                rest.append(c)
                        cmds = rest
                        i = 0
                    for c in cmds[i:]:
                        threads[tid].append((cl, c, slot_counter[0]))
                        slot_counter[0] += 1
            # classify per thread into segments (fpClassify)
            plan = []  # per tid: list of segments; segment = {'lane': {lane: [entries]}, 'barrier': entry|None}
            for tid in range(nthreads):
                segs = [{"lanes": {}, "barrier": None, "order": []}]
                for cl, c, slot in threads[tid]:
                    kind = d.classify(c, observed)
                    seg = segs[-1]
                    if kind[0] == "lane":
                        e = {"cl": cl, "cmd": c, "slot": slot, "steps": d.steps(c), "out": [], "parts": None}
                        seg["lanes"].setdefault(kind[1], []).append(e)
                        seg["order"].append(e)
                    elif kind[0] == "split":
                        whole = {"cl": cl, "cmd": c, "slot": slot, "out": [], "parts": []}
                        seg["order"].append(whole)
                        for lane, ks in kind[1].items():
                            p = {"cl": cl, "cmd": c, "steps": d.steps(c, ks), "out": [], "keys": ks, "whole": whole}
                            whole["parts"].append(p)
                            target = seg
                            if "split_parts_cross_segments" in self.flags and len(whole["parts"]) > 1:
                                # BROKEN: later parts land in the next segment (a barrier-less cut)
                                segs.append({"lanes": {}, "barrier": None, "order": [], "fake": True})
                                target = segs[-1]
                            target["lanes"].setdefault(lane, []).append(p)
                    else:
                        seg["barrier"] = {"cl": cl, "cmd": c, "slot": slot}
                        segs.append({"lanes": {}, "barrier": None, "order": []})
                plan.append(segs)
            # ---- write step: fpExecuteWithLanes, thread-major, pending parts run at each barrier
            pending = []  # list of (tid, seg_index)
            serial = [False]
            steps_plan = []  # a flat list of actions: ('phase', parts) | ('barrier', tid, s)
            for tid in range(nthreads):
                if not threads[tid]:
                    continue
                segs = plan[tid]
                for s in range(len(segs)):
                    pending.append((tid, s))
                    if s == len(segs) - 1:
                        break
                    steps_plan.append(("phase", list(pending)))
                    pending = []
                    steps_plan.append(("barrier", tid, s))
            steps_plan.append(("phase", list(pending)))

            def rec_actions(ai):
                if ai == len(steps_plan):
                    # ---- REPLY phase: deliver in thread-major batch order (fpDeliverRange)
                    for tid in range(nthreads):
                        for cl, c, slot in threads[tid]:
                            d.replies.setdefault(cl, []).append(d.pending_reply[slot])
                    yield from rec_iterations(d, it + 1, newpos, None)
                    return
                act = steps_plan[ai]
                snapshot = (dict(d.kv), {cl: dict(w) for cl, w in d.watch.items()}, {cl: list(v) for cl, v in d.replies.items()}, list(d.lin), list(d.pending_reply), d.exec_count)
                if act[0] == "barrier":
                    _, tid, s = act
                    b = plan[tid][s]["barrier"]
                    if b is None:  # a fake cut (broken variant V5): nothing runs on main here
                        yield from rec_actions(ai + 1)
                        return
                    if "stale_barrier_read" in self.flags:
                        # BROKEN (missing happens-before): the barrier may read the keyspace as it was
                        # before the last lane phase.
                        views = [d.kv, getattr(d, "pre_phase_kv", d.kv)]
                    else:
                        views = [d.kv]
                    for view in views:
                        saved = d.kv
                        d.kv = dict(view)
                        r = d.main_exec(b["cl"], b["cmd"])
                        if view is not saved:
                            # apply the barrier's writes on top of the real state (lost update)
                            real = dict(saved)
                            for k, v in d.kv.items():
                                if view.get(k) != v:
                                    real[k] = v
                            for k in list(real):
                                if k in view and k not in d.kv:
                                    real.pop(k, None)
                            d.kv = real
                        d.lin.append((b["cl"], b["cmd"]))
                        d.pending_reply[b["slot"]] = r
                        if b["cmd"][0] == "WATCH" and "no_issue29_recheck" not in self.flags:
                            serial[0] = True  # fastpathKeyObserversChanged -> rest of the iteration serial
                        yield from rec_actions(ai + 1)
                        d.kv, d.watch, d.replies, d.lin, d.pending_reply, d.exec_count = (dict(snapshot[0]), {cl: dict(w) for cl, w in snapshot[1].items()}, {cl: list(v) for cl, v in snapshot[2].items()}, list(snapshot[3]), list(snapshot[4]), snapshot[5])
                    return
                # lane phase for the pending parts
                parts = act[1]
                lane_seqs = {}
                tordered = []  # entries in T order (fp_parts order, then harvest order): the linearization
                for tid, s in parts:
                    seg = plan[tid][s]
                    for lane, ents in seg["lanes"].items():
                        lane_seqs.setdefault(lane, []).extend(ents)
                    tordered.extend(seg["order"])
                if serial[0]:
                    for e in tordered:
                        r = d.main_exec(e["cl"], e["cmd"])
                        d.lin.append((e["cl"], e["cmd"]))
                        d.pending_reply[e["slot"]] = r
                    yield from rec_actions(ai + 1)
                    d.kv, d.watch, d.replies, d.lin, d.pending_reply, d.exec_count = (dict(snapshot[0]), {cl: dict(w) for cl, w in snapshot[1].items()}, {cl: list(v) for cl, v in snapshot[2].items()}, list(snapshot[3]), list(snapshot[4]), snapshot[5])
                    return
                lanes = sorted(lane_seqs)
                seqs = []
                for lane in lanes:
                    ents = lane_seqs[lane]
                    if "reverse_lane_order" in self.flags and lane == lanes[-1]:
                        ents = list(reversed(ents))  # BROKEN: one lane runs its entries in reverse T order
                    seq = []
                    for e in ents:
                        for st in e["steps"]:
                            seq.append((e, st))
                    seqs.append(seq)
                d.pre_phase_kv = dict(d.kv)
                for order in interleavings(seqs, cap_per_phase):
                    for e in [x for s in seqs for (x, _) in s]:
                        e["out"] = []
                        e.pop("tmp", None)
                    for e, st in order:
                        d.do_step(st, e)
                    if "racy_fast_get" in self.flags:
                        pass
                    # replies of the phase, whole entries assembled from parts (fpSplitAssemble)
                    for e in tordered:
                        if e.get("parts"):
                            if e["cmd"][0] == "MSET":
                                r = "OK"
                            else:
                                vals = {}
                                for p in e["parts"]:
                                    for k, v in zip(p["keys"], p["out"]):
                                        vals[k] = v
                                r = tuple(vals.get(k) for k in e["cmd"][1:])
                        else:
                            r = d.entry_reply(e)
                        d.lin.append((e["cl"], e["cmd"]))
                        d.pending_reply[e["slot"]] = r
                        d.exec_count += 1
                    yield from rec_actions(ai + 1)
                    d.kv, d.watch, d.replies, d.lin, d.pending_reply, d.exec_count = (dict(snapshot[0]), {cl: dict(w) for cl, w in snapshot[1].items()}, {cl: list(v) for cl, v in snapshot[2].items()}, list(snapshot[3]), list(snapshot[4]), snapshot[5])
                    if count[0] >= cap_total:
                        return

            d.pending_reply = [None] * slot_counter[0]
            yield from rec_actions(0)

        d0 = Design(self.shard_of, self.nlanes, self.flags)
        pos0 = {cl: 0 for cl in self.programs}
        yield from rec_iterations(d0, 0, pos0, None)


# ----------------------------------------------------------------------------- checking


def check(scn, verbose=False, **caps):
    """Returns (executions, violations, first_violation_text)."""
    nexec = 0
    bad = 0
    first = None
    for d in scn.executions(**caps):
        nexec += 1
        # G1/G2/G6 by construction: the linearization must list each client's commands in program
        # order and contain every command exactly once; assert it.
        per = {}
        for cl, c in d.lin:
            per.setdefault(cl, []).append(c)
        ok = True
        why = ""
        for cl, prog in scn.programs.items():
            sent = sum(a.get(cl, 0) for a in scn.arrivals)
            if per.get(cl, []) != [c for c in prog[:sent]]:
                ok = False
                why = "G2: linearization is not in %s's program order: %r vs %r" % (cl, per.get(cl), prog[:sent])
        # replay S on the reference: replies and final state must match
        ref = Ref()
        ref_replies = {}
        for cl, c in d.lin:
            ref_replies.setdefault(cl, []).append(ref.run(cl, c))
        if ok:
            for cl in ref_replies:
                if d.replies.get(cl) != ref_replies[cl]:
                    ok = False
                    why = "G1/G4/G5/G6: %s replies %r differ from serial %r (S=%r)" % (cl, d.replies.get(cl), ref_replies[cl], d.lin)
                    break
        if ok and dict(ref.kv) != dict(d.kv):
            ok = False
            why = "G3: final state %r differs from serial %r (S=%r)" % (d.kv, ref.kv, d.lin)
        if not ok:
            bad += 1
            if first is None:
                first = why
    return nexec, bad, first


# ----------------------------------------------------------------------------- scenarios


def hand_scenarios():
    K = ["a", "b", "c"]
    S = []
    # 1. MSET across lanes vs split MGET from another client on another thread, plus a fast GET later
    S.append(("mset-vs-mget", Scenario(
        K, 3, 2,
        {"W": [("MSET", "a", "1", "b", "1"), ("MSET", "a", "2", "b", "2")],
         "R": [("MGET", "a", "b"), ("MGET", "b", "a")],
         "Q": [("GET", "a"), ("GET", "b")]},
        {"W": 0, "R": 1, "Q": 1},
        [{"W": 2, "R": 2}, {"Q": 2}],
        [{0: ["W"], 1: ["R"]}, {1: ["Q"]}])))
    # 2. same-client pipeline across lanes and a cross-lane RENAME barrier from another client
    S.append(("pipeline-rename", Scenario(
        K, 3, 2,
        {"A": [("SET", "a", "x"), ("SET", "b", "y"), ("GET", "a"), ("MGET", "a", "b")],
         "B": [("RENAME", "a", "c"), ("GET", "c"), ("INCR", "b")]},
        {"A": 0, "B": 1},
        [{"A": 4, "B": 3}],
        [{0: ["A"], 1: ["B"]}])))
    # 3. WATCH / EXEC against a lane write (issue 29 shape)
    S.append(("watch-exec", Scenario(
        K, 3, 2,
        {"X": [("WATCH", "a"), ("EXEC", [("SET", "c", "tx")])],
         "Y": [("SET", "a", "1"), ("GET", "c")],
         "Z": [("DEL", "a", "b")]},
        {"X": 0, "Y": 1, "Z": 1},
        [{"X": 1}, {"X": 1, "Y": 2, "Z": 1}],
        [{0: ["X"]}, {0: ["X"], 1: ["Y", "Z"]}])))
    # 4. two iterations: write acknowledged, read later must see it (G6), with INCR counting
    S.append(("ack-then-read", Scenario(
        K, 3, 3,
        {"P": [("INCR", "a"), ("INCR", "a"), ("SET", "b", "v")],
         "Q": [("GET", "a"), ("MGET", "a", "b", "c"), ("INCR", "a")],
         "R": [("MSET", "b", "w", "c", "w"), ("GET", "b")]},
        {"P": 0, "Q": 1, "R": 2},
        [{"P": 3, "R": 1}, {"Q": 3, "R": 1}],
        [{0: ["P"], 2: ["R"]}, {1: ["Q"], 2: ["R"]}])))
    # 5. issue-29 shape: WATCH runs as a barrier on thread 0 while thread 1's lane write to the same key
    #    was classified before the watch existed; EXEC in the next iteration must abort
    S.append(("watch-same-iteration", Scenario(
        K, 3, 2,
        {"X": [("WATCH", "a"), ("EXEC", [("SET", "c", "tx")])],
         "Y": [("SET", "a", "1"), ("SET", "b", "1")],
         "Z": [("GET", "c")]},
        {"X": 0, "Y": 1, "Z": 1},
        [{"X": 1, "Y": 2}, {"X": 1, "Z": 1}],
        [{0: ["X"], 1: ["Y"]}, {0: ["X"], 1: ["Z"]}])))
    return S


def random_scenario(seed, nkeys=3, nshards=3, nlanes=2, nclients=3, nthreads=2, maxlen=3):
    rng = random.Random(seed)
    K = ["a", "b", "c", "d"][:nkeys]
    progs = {}
    thread_of = {}
    for i in range(nclients):
        cl = "c%d" % i
        thread_of[cl] = rng.randrange(nthreads)
        prog = []
        for _ in range(rng.randint(1, maxlen)):
            r = rng.random()
            if r < 0.2:
                prog.append(("SET", rng.choice(K), "%d%d" % (i, len(prog))))
            elif r < 0.35:
                prog.append(("GET", rng.choice(K)))
            elif r < 0.5:
                ks = rng.sample(K, 2)
                prog.append(("MSET", ks[0], "%dm%d" % (i, len(prog)), ks[1], "%dm%d" % (i, len(prog))))
            elif r < 0.65:
                ks = rng.sample(K, min(len(K), rng.randint(2, 3)))
                prog.append(("MGET",) + tuple(ks))
            elif r < 0.75:
                prog.append(("INCR", rng.choice(K)))
            elif r < 0.83:
                prog.append(("DEL",) + tuple(rng.sample(K, rng.randint(1, 2))))
            elif r < 0.91:
                ks = rng.sample(K, 2)
                prog.append(("RENAME", ks[0], ks[1]))
            else:
                k = rng.choice(K)
                prog.append(("WATCH", k))
                prog.append(("EXEC", [("SET", rng.choice(K), "tx%d" % i)]))
        progs[cl] = prog
    # two iterations; each client's commands split at a random point
    arr = [{}, {}]
    for cl, prog in progs.items():
        cut = rng.randint(0, len(prog))
        if cut:
            arr[0][cl] = cut
        if len(prog) - cut:
            arr[1][cl] = len(prog) - cut
    orders = []
    for it in range(2):
        o = {}
        for tid in range(nthreads):
            cls = [cl for cl in progs if thread_of[cl] == tid and arr[it].get(cl)]
            rng.shuffle(cls)
            o[tid] = cls
        orders.append(o)
    return Scenario(K, nshards, nlanes, progs, thread_of, arr, orders)


VARIANTS = [
    ("correct", ()),
    ("V1 reverse_lane_order", ("reverse_lane_order",)),
    ("V2 no_barrier_for_cross_lane", ("no_barrier_for_cross_lane",)),
    ("V3 fast_get_ignores_inflight", ("fast_get_ignores_inflight",)),
    ("V4 stale_barrier_read (missing happens-before)", ("stale_barrier_read",)),
    ("V5 split_parts_cross_segments", ("split_parts_cross_segments",)),
    ("V6 no_issue29_recheck", ("no_issue29_recheck",)),
]


def main():
    nseeds = 30
    if "--seeds" in sys.argv:
        nseeds = int(sys.argv[sys.argv.index("--seeds") + 1])
    scenarios = hand_scenarios() + [("rand%d" % s, random_scenario(s)) for s in range(nseeds)]
    print("scenarios: %d (5 hand-made, %d random)" % (len(scenarios), nseeds))
    summary = []
    for vname, flags in VARIANTS:
        tot_exec = 0
        tot_bad = 0
        bad_scn = 0
        first = None
        for sname, scn in scenarios:
            scn.flags = set(flags)
            n, bad, why = check(scn)
            tot_exec += n
            tot_bad += bad
            if bad:
                bad_scn += 1
                if first is None:
                    first = (sname, why)
        summary.append((vname, tot_exec, tot_bad, bad_scn, first))
        status = "PASS (no violation)" if tot_bad == 0 else "VIOLATION FOUND"
        print("%-50s executions=%-7d violating=%-6d scenarios_hit=%-3d %s" % (vname, tot_exec, tot_bad, bad_scn, status))
        if first:
            print("    first: scenario %s: %s" % (first[0], first[1][:400]))
    ok = summary[0][2] == 0 and all(s[2] > 0 for s in summary[1:])
    print("RESULT:", "correct design clean, every broken variant detected" if ok else "UNEXPECTED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
