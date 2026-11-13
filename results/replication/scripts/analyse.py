#!/usr/bin/env python3
"""Summarise the cross-host replication runs in xhost-repl/runs/ into one table per run and a per-cell summary.

Per run: achieved SET/s (cachecannon result), set p99, lag (master_repl_offset - slave_repl_offset, bytes) over the
scored window (samples after the first 15 s of the sampler, which covers prefill+warmup approx), max lag, replication
stream rate (offset delta per second), WAIT time, digest equality, ENA allowance deltas per host, replica counters.
Writes xhost-repl/summary.tsv and prints a markdown table.
"""
import glob
import json
import os
import re
import statistics

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "xhost-repl")


def ena_counts(text):
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"(\w+_allowance_exceeded):\s+(\d+)", text)}


def info_field(text, key):
    m = re.search(r"^" + re.escape(key) + r":(\S+)", text or "", re.M)
    return float(m.group(1)) if m else None


def cc_result(path):
    if not os.path.exists(path):
        return None
    res = None
    for line in open(path):
        if line.startswith("{") and '"type":"result"' in line.replace(" ", ""):
            res = json.loads(line)
    return res


def samples(path):
    rows, cur = [], None
    for line in open(path):
        line = line.strip()
        if line.startswith("T "):
            cur = {"t": float(line[2:])}
            rows.append(cur)
        elif cur is None:
            continue
        elif line.startswith("master_repl_offset:"):
            cur["p"] = int(line.split(":")[1])
        elif line.startswith("R_slave_repl_offset:"):
            cur["r"] = int(line.split(":")[1])
        elif line.startswith("SS_send"):
            cur["send_bps"] = float(re.sub(r"[^0-9.]", "", line.split()[1]))
        elif line.startswith("SS_bytes_acked:"):
            cur["acked"] = int(line.split(":")[1])
    return [r for r in rows if "p" in r and "r" in r]


def run_row(d):
    rec = json.load(open(os.path.join(d, "run.json")))
    w = cc_result(os.path.join(d, "writer.out")) or {}
    rd = cc_result(os.path.join(d, "reader.out"))
    s = samples(os.path.join(d, "samples.txt"))
    t0 = s[0]["t"] if s else 0
    win = [x for x in s if 15 <= x["t"] - t0 <= 15 + rec["duration"]]
    lags = [x["p"] - x["r"] for x in win]
    rate = None
    if len(win) >= 2:
        rate = (win[-1]["p"] - win[0]["p"]) / (win[-1]["t"] - win[0]["t"])
    ena = {}
    for h in ("C", "S", "R"):
        a, b = ena_counts(rec.get("ena_t0", {}).get(h, "")), ena_counts(rec.get("ena_t1", {}).get(h, ""))
        ena[h] = sum(b[k] - a.get(k, 0) for k in b)
    ri0, ri1 = rec.get("replica_info_t0", ""), rec.get("replica_info_t1", "")

    def dlt(k):
        a, b = info_field(ri0, k), info_field(ri1, k)
        return None if a is None or b is None else b - a

    return {
        "run": os.path.basename(d), "label": rec["label"], "rate": rec["rate"], "rep": rec["rep"], "reader": rec["reader"],
        "achieved": w.get("throughput"), "set_p99_us": (w.get("set") or {}).get("p99_us"), "w_err_pct": w.get("err_pct"),
        "lag_mean_B": statistics.mean(lags) if lags else None, "lag_max_B": max(lags) if lags else None,
        # The sampler reads the primary offset, then the replica offset a few ms later, so lag is biased negative
        # by (sampling skew x stream rate). lag_ms = lag / stream rate; values near -3 ms mean "below resolution".
        "lag_mean_ms": (statistics.mean(lags) / rate * 1000) if lags and rate else None,
        "lag_max_ms": (max(lags) / rate * 1000) if lags and rate else None,
        "stream_Bps": rate, "wait_s": rec.get("wait_s"), "wait": rec.get("wait"), "digest_equal": rec.get("digest_equal"),
        "ena_C": ena["C"], "ena_S": ena["S"], "ena_R": ena["R"],
        "repl_parallel_applied": dlt("repl_parallel_applied"), "repl_lane_reads": dlt("repl_lane_reads"),
        "repl_lane_barriers": dlt("repl_lane_barriers"),
        "reader_gets": rd.get("throughput") if rd else None,
        "reader_p50_us": (rd.get("get") or {}).get("p50_us") if rd else None,
        "reader_p99_us": (rd.get("get") or {}).get("p99_us") if rd else None,
        "reader_p999_us": (rd.get("get") or {}).get("p999_us") if rd else None,
    }


def main():
    rows = [run_row(d) for d in sorted(glob.glob(os.path.join(OUT, "runs", "*"))) if os.path.exists(os.path.join(d, "run.json"))]
    keys = list(rows[0].keys()) if rows else []
    with open(os.path.join(OUT, "summary.tsv"), "w") as f:
        f.write("\t".join(keys) + "\n")
        for r in rows:
            f.write("\t".join("" if r[k] is None else str(r[k]) for k in keys) + "\n")
    print("| run | achieved SET/s | set p99 us | lag mean ms | lag max ms | stream MB/s | WAIT s | digest eq | ENA C/S/R | parallel_applied | lane_barriers |")
    print("|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|")
    for r in rows:
        f = lambda v, fmt="{:,.0f}": "-" if v is None else fmt.format(v)
        print(f"| {r['run']} | {f(r['achieved'])} | {f(r['set_p99_us'])} | {f(r['lag_mean_ms'], '{:.1f}')} | {f(r['lag_max_ms'], '{:.1f}')} | "
              f"{f(r['stream_Bps'] and r['stream_Bps'] / 1e6, '{:.1f}')} | {f(r['wait_s'], '{:.1f}')} | {r['digest_equal']} | "
              f"{r['ena_C']}/{r['ena_S']}/{r['ena_R']} | {f(r['repl_parallel_applied'])} | {f(r['repl_lane_barriers'])} |")


if __name__ == "__main__":
    main()
