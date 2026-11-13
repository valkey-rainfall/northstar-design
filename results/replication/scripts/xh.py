#!/usr/bin/env python3
"""Manual cross-host replication harness (three hosts: primary, replica, writer).

Primary valkey-server on the server host, replica on the replica host, SET stream from cachecannon
(build e545c26) on the client host. Replication crosses the real NIC (one TCP flow primary -> replica).
Orchestrated from a control host over ssh. Host names, private addresses and the key file come from the
environment: XH_KEY, XH_C, XH_S, XH_R (user@host) and XH_C_IP, XH_S_IP, XH_R_IP. The values below are
documentation placeholders (198.51.100.0/24).

Binaries: valkey-server builds copied to ~/xh/<label>/ on the primary and the replica (sha256 recorded in
binaries.json by the run).
"""
import json
import os
import re
import subprocess
import sys
import time

KEY = os.path.expanduser(os.environ.get("XH_KEY", "~/xh-key"))
SSHO = ["-o", "StrictHostKeyChecking=yes", "-o", "NumberOfPasswordPrompts=0", "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no", "-o", "ConnectTimeout=10", "-i", KEY]
HOSTS = {
    "C": (os.environ.get("XH_C", "operator@client-host"), os.environ.get("XH_C_IP", "198.51.100.12"), "ens68"),
    "S": (os.environ.get("XH_S", "operator@server-host"), os.environ.get("XH_S_IP", "198.51.100.10"), "enP6s65"),
    "R": (os.environ.get("XH_R", "operator@replica-host"), os.environ.get("XH_R_IP", "198.51.100.11"), "enP6s65"),
}
SHA = {"S1": "92709489481acf0e12ac0008cdacbff376c9293f", "P9": "91dbb9c36787fd31e13fea59899b7f36f2804eaa",
       "STOCK": "2a23bcda07f141235f0310d9b20c42f17db90b46"}
SRC = {"S1": "valkey-rainfall", "P9": "valkey-rainfall", "STOCK": "valkey"}
# PROBE: built by hand in ~/xh/PROBE-src on server-host (e82fc7da + a diagnostic counter patch, not published), copied
# to ~/xh/PROBE/valkey-server on server and replica by "stageprobe". Not in SHA/SRC so "stage" leaves it alone.
# Control variants for the closed-loop ACK-timeout finding (2026-10-31 01:35 UTC):
#   base       G5 args (lanes forced, repl-stream-sender yes, replica-parallel-apply yes)
#   noapply    as base but replica-parallel-apply no
#   nosender   as base but repl-stream-sender no
#   nolanes    no lane args, no sender, replica-parallel-apply no (proof-of-concept build with its features off)
#   stock      no proof-of-concept args at all (only valid config for STOCK)
VARIANTS = {
    "base": ("--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes",
             "--replica-parallel-apply yes"),
    "noapply": ("--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes",
                "--replica-parallel-apply no"),
    "nosender": ("--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender no",
                 "--replica-parallel-apply yes"),
    "nolanes": ("--repl-stream-sender no", "--replica-parallel-apply no"),
    "stock": ("", ""),
    # repl-stream-sender only adopts a replica that did NOT get a diskless (socket) RDB: replication.c sets
    # stream_ineligible at the diskless RDB -> stream handoff. Disk-based sync lets the sender adopt it.
    "sender": ("--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes "
               "--repl-diskless-sync no", "--replica-parallel-apply yes"),
    "nosender2": ("--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender no "
                  "--repl-diskless-sync no", "--replica-parallel-apply yes"),
}
PPORT, RPORT = 51000, 51001
CCBIN = "$HOME/cachecannon-current/target/release/cachecannon"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "xhost-repl")
RATES = [50000, 200000, 500000, 1000000, 0]  # 0 = closed loop (max)
REPS = 3
DUR = 60
COMMON = ("--save '' --appendonly no --protected-mode no --enable-debug-command yes "
          "--client-output-buffer-limit 'replica 0 0 0' --repl-backlog-size 1gb --io-threads 5 --daemonize yes")
PRIMARY_ARGS = "--io-threads-parallel-writes-min 1 --keyspace-shard-bits 8 --repl-stream-sender yes"
REPLICA_ARGS = "--replica-parallel-apply yes"


def ssh(h, cmd, check=True, timeout=300, stdin=None):
    p = subprocess.run(["ssh"] + SSHO + [HOSTS[h][0], cmd], capture_output=True, text=stdin is None,
                       timeout=timeout, input=stdin)
    if check and p.returncode != 0:
        raise RuntimeError(f"{h}: {cmd[:120]} -> {p.returncode}: {p.stderr[-500:]}")
    return p.stdout


def log(msg):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg
    print(line, flush=True)
    with open(os.path.join(OUT, "harness.log"), "a") as f:
        f.write(line + "\n")


def cli(h, port, cmd):
    return ssh(h, f"~/xh/valkey-cli -h {HOSTS[h][1]} -p {port} {cmd}", check=False)


SAMPLER = r"""#!/usr/bin/env bash
# xh sampler: every 1 s, primary and replica replication offsets, replica link state, and the replication
# flow's TCP state (ss -tin). Runs on server-host for $1 seconds, writes to $2.
END=$(( $(date +%s) + $1 ))
while [ "$(date +%s)" -lt "$END" ]; do
  echo "T $(date +%s.%N)"
  ~/xh/valkey-cli -h 198.51.100.10 -p 51000 info replication | grep -E '^(master_repl_offset|slave0):'
  ~/xh/valkey-cli -h 198.51.100.11 -p 51001 info replication | grep -E '^(slave_repl_offset|master_link_status|master_last_io_seconds_ago):' | sed 's/^/R_/'
  ss -tin state established "( sport = :51000 )" dst 198.51.100.11 | tr -s ' ' | grep -oE '(bytes_acked|bytes_sent|cwnd|rtt|delivery_rate|send|pacing_rate)[: ][^ ]+' | sed 's/^/SS_/'
  sleep 1
done >> "$2"
"""


DIAG = r"""#!/usr/bin/env bash
# xh diag: every 5 s, per-thread CPU of our server (top -H, 1 s interval, second frame) and, on the primary,
# CLIENT LIST TYPE REPLICA. $1 = seconds, $2 = role (primary|replica), $3 = out file. Runs on cpu 91.
END=$(( $(date +%s) + $1 ))
if [ "$2" = primary ]; then PIDF=~/xh/primary.pid; IP=198.51.100.10; PORT=51000; else PIDF=~/xh/replica.pid; IP=198.51.100.11; PORT=51001; fi
while [ "$(date +%s)" -lt "$END" ]; do
  echo "T $(date +%s.%N)"
  top -H -b -n 2 -d 1 -p "$(cat $PIDF)" | awk 'BEGIN{f=0} /^top -/{f++} f==2 && $1 ~ /^[0-9]+$/ {print "TOP", $1, $9, $12}'
  if [ "$2" = primary ]; then ~/xh/valkey-cli -h $IP -p $PORT client list type replica | sed 's/^/CL /';
    ~/xh/valkey-cli -h $IP -p $PORT info everything | grep -E '^(probe_|repl_sender_)' | tr -d '\r' | sed 's/^/INFO /'; fi
  if [ "$2" = replica ]; then ~/xh/valkey-cli -h $IP -p $PORT client list type master | sed 's/^/CLM /'; ss -tin state established "( dport = :51000 )" | tr -s ' ' | grep -oE '(bytes_sent|bytes_acked|bytes_received|unacked|notsent)[: ][^ ]+' | sed 's/^/SSR_/'; fi
  sleep 3
done >> "$3"
"""


def stage():
    os.makedirs(OUT, exist_ok=True)
    stage_dir = os.path.join(os.environ.get("WORK", "/tmp"), "xh-stage")
    os.makedirs(stage_dir, exist_ok=True)
    ssh("S", "mkdir -p ~/xh && cp ~/runner/valkey-cli ~/xh/valkey-cli")
    ssh("R", "mkdir -p ~/xh")
    ssh("C", "mkdir -p ~/xh")
    for label, sha in SHA.items():
        src = f"~/build_cache/{SRC[label]}/{sha}/d41d8cd98f00b204/valkey-server"
        ssh("S", f"mkdir -p ~/xh/{label} && cp {src} ~/xh/{label}/valkey-server")
        local = os.path.join(stage_dir, f"{label}-valkey-server")
        with open(local, "wb") as f:
            f.write(subprocess.run(["ssh"] + SSHO + [HOSTS["S"][0], f"cat ~/xh/{label}/valkey-server"],
                                   capture_output=True, check=True).stdout)
        ssh("R", f"mkdir -p ~/xh/{label} && cat > ~/xh/{label}/valkey-server && chmod 755 ~/xh/{label}/valkey-server",
            stdin=open(local, "rb").read())
    local = os.path.join(stage_dir, "valkey-cli")
    with open(local, "wb") as f:
        f.write(subprocess.run(["ssh"] + SSHO + [HOSTS["S"][0], "cat ~/xh/valkey-cli"], capture_output=True,
                               check=True).stdout)
    for h in ("R", "C"):
        ssh(h, "cat > ~/xh/valkey-cli && chmod 755 ~/xh/valkey-cli", stdin=open(local, "rb").read())
    ssh("S", "cat > ~/xh/sampler.sh && chmod 755 ~/xh/sampler.sh", stdin=SAMPLER.encode())
    for h in ("S", "R"):
        ssh(h, "cat > ~/xh/diag.sh && chmod 755 ~/xh/diag.sh", stdin=DIAG.encode())
    sums = {h: ssh(h, "sha256sum ~/xh/*/valkey-server ~/xh/valkey-cli") for h in ("S", "R")}
    sums["C"] = ssh("C", "sha256sum ~/xh/valkey-cli; " + CCBIN + " --version")
    sums["build_cache"] = ssh("S", "sha256sum " + " ".join(
        f"~/build_cache/{SRC[k]}/{v}/d41d8cd98f00b204/valkey-server" for k, v in SHA.items()))
    json.dump(sums, open(os.path.join(OUT, "binaries.json"), "w"), indent=1)
    log("staged: " + json.dumps(sums))


def toml(rate, prefill, target, cmd, conns, threads, cpus, pipeline, dur):
    w = "get = 0\nset = 100" if cmd == "set" else "get = 100\nset = 0"
    rl = f"\nrate_limit = {rate}" if rate else ""
    return f"""[general]
duration = "{dur}s"
warmup = "5s"
threads = {threads}
cpu_list = "{cpus}"
io_engine = "uring"

[target]
endpoints = ["{target}"]
protocol = "resp"

[connection]
connections = {conns}
pipeline_depth = {pipeline}

[workload]
prefill = {'true' if prefill else 'false'}{rl}

[workload.keyspace]
length = 16
count = 3000000
distribution = "uniform"

[workload.commands]
{w}
delete = 0

[workload.values]
length = 16

[timestamps]
enabled = true
mode = "userspace"

[admin]
format = "json"
"""


def ena():
    return {h: ssh(h, f"ethtool -S {HOSTS[h][2]} | grep allowance_exceeded") for h in HOSTS}


def info(h, port, sections):
    return cli(h, port, "info " + " ".join(sections))


def start_pair(label, variant="base", tag="run"):
    pa, ra = VARIANTS[variant]
    for h in ("S", "R"):
        ssh(h, f"mkdir -p /dev/shm/xh-{h}")
    rcmd = (f"taskset -c 0-7 ~/xh/{label}/valkey-server --bind {HOSTS['R'][1]} --port {RPORT} --dir /dev/shm/xh-R "
            f"--logfile $HOME/xh/replica-{tag}.log --pidfile $HOME/xh/replica.pid {COMMON} {ra}")
    pcmd = (f"taskset -c 0-7 ~/xh/{label}/valkey-server --bind {HOSTS['S'][1]} --port {PPORT} --dir /dev/shm/xh-S "
            f"--logfile $HOME/xh/primary-{tag}.log --pidfile $HOME/xh/primary.pid {COMMON} {pa}")
    ssh("R", rcmd)
    ssh("S", pcmd)
    for h, port in (("R", RPORT), ("S", PPORT)):
        for _ in range(30):
            if "PONG" in cli(h, port, "ping"):
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"{h} server did not answer PING")
    cli("R", RPORT, f"replicaof {HOSTS['S'][1]} {PPORT}")
    for _ in range(60):
        if "master_link_status:up" in info("R", RPORT, ["replication"]):
            return
        time.sleep(1)
    raise RuntimeError("replica link not up")


def stop_pair():
    for h, port in (("S", PPORT), ("R", RPORT)):
        cli(h, port, "shutdown nosave")
    time.sleep(2)
    # /dev/shm/xh-S and xh-R are kept and reused: --save '' and appendonly no, so no data persists there.


def one(label, rate, rep, reader=False, variant="base"):
    d = os.path.join(OUT, "runs", f"{label}-{'max' if rate == 0 else str(rate // 1000) + 'k'}-r{rep}"
                     + ("-reader" if reader else "") + ("" if variant == "base" else "-" + variant))
    os.makedirs(d, exist_ok=True)
    rec = {"label": label, "sha": SHA[label], "rate": rate, "rep": rep, "reader": reader, "duration": DUR,
           "variant": variant, "primary_args": f"{COMMON} {VARIANTS[variant][0]}",
           "replica_args": f"{COMMON} {VARIANTS[variant][1]}"}
    tag = os.path.basename(d)
    start_pair(label, variant, tag)
    try:
        rec["replica_info_t0"] = info("R", RPORT, ["stats", "fastpath"])
        rec["primary_info_t0"] = info("S", PPORT, ["stats", "fastpath"])
        rec["primary_sender_t0"] = cli("S", PPORT, "info everything | grep -E '^(probe_|repl_sender_)'")
        ssh("C", "cat > ~/xh/w.toml", stdin=toml(rate, True, f"{HOSTS['S'][1]}:{PPORT}", "set", 2400, 32,
                                                  "16-47", 10, DUR).encode())
        if reader:
            ssh("C", "cat > ~/xh/r.toml", stdin=toml(0, False, f"{HOSTS['R'][1]}:{RPORT}", "get", 400, 16,
                                                      "48-63", 1, DUR).encode())
        rec["ena_t0"] = ena()
        ssh("S", f"rm -f ~/xh/samples.txt; (nohup taskset -c 90 ~/xh/sampler.sh {DUR + 25} ~/xh/samples.txt "
                 f">/dev/null 2>&1 &)")
        if rate == 0:  # closed loop: per-thread CPU on both servers, CLIENT LIST of the replica on the primary
            ssh("S", f"rm -f ~/xh/diag.txt; (nohup taskset -c 91 ~/xh/diag.sh {DUR + 20} primary ~/xh/diag.txt >/dev/null 2>&1 &)")
            ssh("R", f"rm -f ~/xh/diag.txt; (nohup taskset -c 91 ~/xh/diag.sh {DUR + 20} replica ~/xh/diag.txt >/dev/null 2>&1 &)")
        wcmd = f"numactl --membind=0 {CCBIN} ~/xh/w.toml > ~/xh/w.out 2>&1"
        if reader:
            # reader starts 10 s later so the writer's prefill is done and the stream is running
            wcmd = (f"(sleep 10; numactl --membind=0 {CCBIN} ~/xh/r.toml > ~/xh/r.out 2>&1) & "
                    f"{wcmd}; wait")
        t0 = time.time()
        ssh("C", wcmd, check=False, timeout=DUR + 300)
        rec["writer_wall_s"] = time.time() - t0
        rec["ena_t1"] = ena()
        rec["primary_info_t1"] = info("S", PPORT, ["stats", "fastpath", "replication"])
        # WAIT from a new connection returns at once (that client wrote nothing, so its target offset is 0).
        # Instead poll until the replica's slave_repl_offset reaches the primary's master_repl_offset (max 300 s).
        t1 = time.time()
        target = int(re.search(r"master_repl_offset:(\d+)", rec["primary_info_t1"]).group(1))
        caught = False
        while time.time() - t1 < 300:
            m = re.search(r"slave_repl_offset:(\d+)", info("R", RPORT, ["replication"]))
            if m and int(m.group(1)) >= target:
                caught = True
                break
            time.sleep(1)
        rec["catchup_target_offset"] = target
        rec["catchup_ok"] = caught
        rec["catchup_s"] = time.time() - t1
        rec["wait"] = "not used (see catchup_*)"
        rec["wait_s"] = rec["catchup_s"]
        rec["replica_info_t1"] = info("R", RPORT, ["stats", "fastpath", "replication", "keyspace"])
        rec["digest_primary"] = cli("S", PPORT, "debug digest").strip()
        rec["digest_replica"] = cli("R", RPORT, "debug digest").strip()
        rec["digest_equal"] = rec["digest_primary"] == rec["digest_replica"] and rec["digest_primary"] != ""
        time.sleep(max(0, DUR + 27 - (time.time() - t0)))
        open(os.path.join(d, "writer.out"), "w").write(ssh("C", "cat ~/xh/w.out", check=False))
        if reader:
            open(os.path.join(d, "reader.out"), "w").write(ssh("C", "cat ~/xh/r.out", check=False))
        if rate == 0:
            open(os.path.join(d, "diag-primary.txt"), "w").write(ssh("S", "cat ~/xh/diag.txt", check=False))
            open(os.path.join(d, "diag-replica.txt"), "w").write(ssh("R", "cat ~/xh/diag.txt", check=False))
        open(os.path.join(d, "samples.txt"), "w").write(ssh("S", "cat ~/xh/samples.txt", check=False))
        open(os.path.join(d, "primary.log"), "w").write(ssh("S", f"cat ~/xh/primary-{tag}.log", check=False))
        open(os.path.join(d, "replica.log"), "w").write(ssh("R", f"cat ~/xh/replica-{tag}.log", check=False))
    finally:
        stop_pair()
        json.dump(rec, open(os.path.join(d, "run.json"), "w"), indent=1)
    log(f"done {d} digest_equal={rec.get('digest_equal')} wait={rec.get('wait')} wait_s={rec.get('wait_s', 0):.1f}")


def main():
    os.makedirs(OUT, exist_ok=True)
    mode = sys.argv[1]
    labels = sys.argv[2:] or ["S1", "P9"]
    if mode == "stage":
        stage()
    elif mode == "run":
        for rate in RATES:
            for rep in range(1, REPS + 1):
                for label in labels:  # alternate commits inside each rate
                    try:
                        one(label, rate, rep)
                    except Exception as e:  # record and continue
                        log(f"FAIL {label} {rate} r{rep}: {e}")
    elif mode == "reader":
        for label in labels:
            try:
                one(label, 500000, 1, reader=True)
            except Exception as e:
                log(f"FAIL reader {label}: {e}")
    elif mode == "controls":
        # closed-loop ACK-timeout controls: variant matrix at max rate, 1 rep each (2 for base on STOCK pairing)
        plan = [("S1", "base"), ("S1", "noapply"), ("S1", "nosender"), ("S1", "nolanes"), ("STOCK", "stock"),
                ("P9", "noapply"), ("P9", "nosender"), ("P9", "nolanes"), ("STOCK", "stock")]
        for i, (label, variant) in enumerate(plan):
            try:
                one(label, 0, 11 + i // 5, variant=variant)
            except Exception as e:
                log(f"FAIL controls {label} {variant}: {e}")
    elif mode == "ackdiag":
        for i, label in enumerate(labels):
            try:
                one(label, 0, 21 + i, variant="base")
            except Exception as e:
                log(f"FAIL ackdiag {label}: {e}")
    elif mode in ("stageprobe", "stagefix"):
        blabel = "PROBE" if mode == "stageprobe" else "FIX"
        stage_dir = os.path.join(os.environ.get("WORK", "/tmp"), "xh-stage")
        os.makedirs(stage_dir, exist_ok=True)
        local = os.path.join(stage_dir, f"{blabel}-valkey-server")
        with open(local, "wb") as f:
            f.write(subprocess.run(["ssh"] + SSHO + [HOSTS["S"][0], f"cat ~/xh/{blabel}/valkey-server"],
                                   capture_output=True, check=True).stdout)
        ssh("R", f"mkdir -p ~/xh/{blabel} && cat > ~/xh/{blabel}/valkey-server && chmod 755 ~/xh/{blabel}/valkey-server",
            stdin=open(local, "rb").read())
        log(f"{mode}: " + ssh("S", f"sha256sum ~/xh/{blabel}/valkey-server").strip() + " | " +
            ssh("R", f"sha256sum ~/xh/{blabel}/valkey-server").strip())
    elif mode == "probe":
        SHA["PROBE"] = "e82fc7da5cfcaf26b67fe9e9af7f51abce3c42bd+probe.patch"
        rep = int(labels[0]) if labels and labels[0].isdigit() else 31
        variant = labels[1] if len(labels) > 1 else "base"
        try:
            one("PROBE", 0, rep, variant=variant)
        except Exception as e:
            log(f"FAIL probe {rep} {variant}: {e}")
    elif mode == "fix":
        # FIX: audit/phase13-ack f65f429e (parent e82fc7da), built in ~/xh/FIX-src on server-host
        SHA["FIX"] = "f65f429effe1156eb1942da57856d829213f9a26"
        for rep in (51, 52):
            try:
                one("FIX", 0, rep, variant="base")
            except Exception as e:
                log(f"FAIL fix {rep}: {e}")
    elif mode == "sendertrue":
        for i, (label, variant) in enumerate([("S1", "sender"), ("S1", "nosender2"), ("P9", "sender"),
                                              ("P9", "nosender2")]):
            try:
                one(label, 0, 41 + i // 2, variant=variant)
            except Exception as e:
                log(f"FAIL sendertrue {label} {variant}: {e}")
    elif mode == "smoke":
        global DUR
        DUR = 10
        one(labels[0], 50000, 0)


if __name__ == "__main__":
    main()
