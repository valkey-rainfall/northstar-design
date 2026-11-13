"""Minimal RESP2 client over raw sockets (standard library only), plus helpers shared by the
rt-multikey-atomicity tests: key->shard hash (copy of keyspaceShard in src/db.c), INFO parsing and
engagement counters.
"""
import socket
import time

MASK64 = (1 << 64) - 1


def keyspace_shard(key, bits=8):
    """Python copy of keyspaceShard() from src/db.c (standalone keyspace sharding)."""
    if bits == 0:
        return 0
    s = key.encode() if isinstance(key, str) else key
    n = len(s)
    h = (0x9e3779b97f4a7c15 ^ n) & MASK64
    i = 0
    while n - i >= 8:
        w = int.from_bytes(s[i:i + 8], "little")
        h = ((h ^ w) * 0xff51afd7ed558ccd) & MASK64
        h ^= h >> 32
        i += 8
    w = 0
    for j, b in enumerate(s[i:]):
        w |= b << (8 * j)
    h = ((h ^ w) * 0xc4ceb9fe1a85ec53) & MASK64
    h ^= h >> 29
    return h & ((1 << bits) - 1)


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        elif isinstance(a, int):
            a = str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


class RespError(Exception):
    pass


class Conn:
    def __init__(self, port, host="127.0.0.1", timeout=10.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

    def send(self, *cmds):
        self.s.sendall(b"".join(encode(*c) for c in cmds))

    def _readline(self):
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line = self.buf[:i]
                self.buf = self.buf[i + 2:]
                return line
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("eof")
            self.buf += chunk

    def _readn(self, n):
        while len(self.buf) < n + 2:
            chunk = self.s.recv(max(65536, n + 2 - len(self.buf)))
            if not chunk:
                raise ConnectionError("eof")
            self.buf += chunk
        data = self.buf[:n]
        self.buf = self.buf[n + 2:]
        return data

    def read(self):
        line = self._readline()
        t = line[:1]
        if t == b"+":
            return line[1:]
        if t == b"-":
            return RespError(line[1:].decode())
        if t == b":":
            return int(line[1:])
        if t == b"$":
            n = int(line[1:])
            if n < 0:
                return None
            return self._readn(n)
        if t == b"*":
            n = int(line[1:])
            if n < 0:
                return None
            return [self.read() for _ in range(n)]
        if t == b"_":
            return None
        raise RespError("bad reply type %r" % line)

    def cmd(self, *args):
        self.send(args)
        return self.read()

    def pipeline(self, cmds):
        self.send(*cmds)
        return [self.read() for _ in cmds]


ENGAGE_FIELDS = [
    "fastpath_clients", "fastpath_reads", "fastpath_writes", "fastpath_speculated",
    "fastpath_write_lane_phases", "fastpath_write_lane_entries", "fastpath_write_barriers",
    "fastpath_write_serial_segments", "staged_iterations", "staged_write_phases", "staged_apply_phases",
    "repl_lane_reads", "repl_lane_barriers", "keyspace_shard_bits",
]


def info(port, section="all"):
    c = Conn(port)
    raw = c.cmd("INFO", section)
    c.close()
    d = {}
    for line in raw.decode().split("\r\n"):
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            d[k] = v
    return d


def engagement(port):
    d = info(port)
    out = {}
    for f in ENGAGE_FIELDS:
        if f in d:
            out[f] = d[f]
    out["io_threads"] = d.get("io_threads_running", "?")
    return out


def engagement_delta(before, after):
    out = {}
    for k, v in after.items():
        try:
            out[k] = int(v) - int(before.get(k, 0))
        except (TypeError, ValueError):
            out[k] = v
    return out


def fmt_engagement(d):
    keys = ["fastpath_clients", "fastpath_speculated", "fastpath_write_lane_phases", "fastpath_write_lane_entries",
            "fastpath_write_barriers", "fastpath_write_serial_segments", "staged_write_phases", "staged_apply_phases",
            "repl_lane_reads", "repl_lane_barriers"]
    return " ".join("%s=%s" % (k, d[k]) for k in keys if k in d)


def wait_ready(port, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            c = Conn(port, timeout=1.0)
            if c.cmd("PING") == b"PONG":
                c.close()
                return True
            c.close()
        except OSError:
            time.sleep(0.1)
    return False
