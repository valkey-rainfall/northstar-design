#!/usr/bin/env python3
"""Phase 23d probe: reply order (G1, G2) of pipelined fast-path clients on C
(ceaa1101d), over TLS and with staged-reply-merge on. Starts one valkey-server per case on 127.0.0.1,
drives N clients with pipelines of mixed SET / INCR / GET / MGET, checks that every client's replies come
back in its send order and equal the values a serial server would give for that client's own keys, and
reads INFO to confirm the clients ran on the fast path. Exit 1 on any difference.

Usage: probe.py <valkey-server> <tls-dir> <case> <port> [clients] [rounds] [ahead]
  ahead 1: each client sends round r+1 before it reads round r's replies, so a client's new commands
  arrive while its previous replies are still undelivered (the fp_inflight gate of da3bdb071).
  case: tcp | tls | merge | merge-tls | ep2 | ep2-tls
        merge = --staged-reply-merge yes (da3bdb071); ep2 = --io-threads 6 --io-threads-epoll-thread yes
        --io-threads-epoll-threads 2 (6b4416f27: two collector threads); -tls = the clients connect over TLS
Needs python3 only (ssl module). The server is stopped with SHUTDOWN NOSAVE.
"""
import os, socket, ssl, subprocess, sys, time

srv, tlsdir, case, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
nclients = int(sys.argv[5]) if len(sys.argv) > 5 else 8
rounds = int(sys.argv[6]) if len(sys.argv) > 6 else 200
ahead = int(sys.argv[7]) if len(sys.argv) > 7 else 0
tls = case.endswith("tls")
merge = case.startswith("merge")
ep2 = case.startswith("ep2")

args = [srv, "--save", "", "--appendonly", "no", "--io-threads", "4", "--loglevel", "warning",
        "--logfile", f"/dev/null", "--bind", "127.0.0.1", "--daemonize", "no"]
if tls:
    args += ["--port", "0", "--tls-port", str(port), "--tls-cert-file", f"{tlsdir}/valkey.crt",
             "--tls-key-file", f"{tlsdir}/valkey.key", "--tls-ca-cert-file", f"{tlsdir}/ca.crt",
             "--tls-auth-clients", "no"]
else:
    args += ["--port", str(port)]
if merge:
    args += ["--staged-reply-merge", "yes"]
if ep2:
    args += ["--io-threads", "6", "--io-threads-epoll-thread", "yes", "--io-threads-epoll-threads", "2"]
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def connect():
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(s)
    return s

def resp(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        a = a if isinstance(a, bytes) else str(a).encode()
        out += b"$%d\r\n%s\r\n" % (len(a), a)
    return out

class Reader:
    def __init__(self, s):
        self.s, self.buf = s, b""
    def line(self):
        while b"\r\n" not in self.buf:
            d = self.s.recv(65536)
            if not d: raise EOFError
            self.buf += d
        l, self.buf = self.buf.split(b"\r\n", 1)
        return l
    def exact(self, n):
        while len(self.buf) < n + 2:
            d = self.s.recv(65536)
            if not d: raise EOFError
            self.buf += d
        v, self.buf = self.buf[:n], self.buf[n + 2:]
        return v
    def reply(self):
        l = self.line()
        t = l[:1]
        if t in b"+-:": return l
        if t == b"$":
            n = int(l[1:])
            return None if n < 0 else self.exact(n)
        if t == b"*":
            n = int(l[1:])
            return None if n < 0 else [self.reply() for _ in range(n)]
        raise ValueError(l)

deadline = time.time() + 20
while True:
    try:
        s = connect(); s.sendall(resp("PING")); r = Reader(s)
        if r.reply() == b"+PONG": break
    except Exception:
        if time.time() > deadline: proc.kill(); sys.exit("server did not start")
        time.sleep(0.1)
s.close()

# Each client owns keys c<i>:a c<i>:b c<i>:n (different shards in general) and runs rounds of a
# pipeline whose expected replies follow from its own history only (per-key order G3 within one client).
fail = 0
socks = [connect() for _ in range(nclients)]
readers = [Reader(s) for s in socks]
big = b"x" * 40000  # spans several TLS records
def send_round(rnd):
    expect = []
    for i, s in enumerate(socks):
        a, b, n = f"c{i}:a", f"c{i}:b", f"c{i}:n"
        v = f"{rnd}-{i}"
        pipe = resp("SET", a, v) + resp("INCR", n) + resp("GET", a) + resp("MSET", a, v + "x", b, big) + \
               resp("MGET", a, b) + resp("GET", n) + resp("GET", b) + resp("INCR", n) + resp("GET", a)
        s.sendall(pipe)
        expect.append([b"+OK", b":%d" % (2 * rnd + 1), v.encode(), b"+OK", [v.encode() + b"x", big],
                       b"%d" % (2 * rnd + 1), big, b":%d" % (2 * rnd + 2), v.encode() + b"x"])
    return expect

def read_round(rnd, expect):
    global fail
    for i, r in enumerate(readers):
        got = [r.reply() for _ in range(9)]
        if got != expect[i]:
            fail += 1
            if fail <= 3:
                print(f"round {rnd} client {i}: got {[g if not isinstance(g, list) else [x[:12] for x in g] for g in got]}")

pending = []
for rnd in range(rounds):
    pending.append((rnd, send_round(rnd)))
    while len(pending) > ahead:
        r0, e0 = pending.pop(0)
        read_round(r0, e0)
    if fail > 3: break
while pending and fail <= 3:
    r0, e0 = pending.pop(0)
    read_round(r0, e0)

# INFO: the clients must have been on the fast path, and the staged loop must have iterated.
s = connect(); s.sendall(resp("INFO", "everything")); r = Reader(s); info = r.reply().decode(); s.close()
fields = dict(l.split(":", 1) for l in info.splitlines() if ":" in l and not l.startswith("#"))
want = {"fastpath_clients", "fastpath_batches", "fastpath_speculated", "staged_iterations", "fastpath_writes",
        "staged_epoll_thread", "staged_main_lane", "staged_reply_phases"}
summary = {k: fields.get(k) for k in sorted(want)}
print(f"case {case}: clients {nclients} rounds {rounds} ahead {ahead} differences {fail}; {summary}")
if merge and int(fields.get("staged_reply_phases", "1")) != 0:
    print("NOTE: reply phases ran under staged-reply-merge (a hand-back, cron or tracking prefix forces them)")
if int(fields.get("fastpath_batches", "0")) == 0:
    print("FAIL: no fast-path batch: the clients did not run on the fast path"); fail += 1
if int(fields.get("staged_iterations", "0")) == 0:
    print("FAIL: the staged loop did not run"); fail += 1
for sk in socks: sk.close()
try:
    s = connect(); s.sendall(resp("SHUTDOWN", "NOSAVE")); s.settimeout(5); s.recv(10); s.close()
except Exception:
    pass
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    print("FAIL: the server did not stop after SHUTDOWN NOSAVE"); fail += 1; proc.kill(); proc.wait()
sys.exit(1 if fail else 0)
