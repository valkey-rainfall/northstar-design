#!/bin/bash
# Start or stop a valkey-server for the linearize runs. Bind 127.0.0.1 only, cores 4-7 by default.
# Usage: server.sh start <port> <mode> [extra args]   mode: lanes | baseline
#        server.sh stop <port>
# Env: VK_SRC (dir with valkey-server), RUNDIR, CORES
set -u
VK_SRC=${VK_SRC:-${WORK}/wt-linearize/src}
CORES=${CORES:-4-7}
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
op=$1; port=$2; shift 2
case "$op" in
  start)
    mode=$1; shift
    mkdir -p "$RUNDIR/$port"
    case "$mode" in
      lanes)    extra="--io-threads 5 --io-threads-parallel-writes-min 1" ;;
      baseline) extra="--io-threads 1 --io-threads-fast-path no" ;;
      *) echo "bad mode" >&2; exit 1 ;;
    esac
    taskset -c "$CORES" "$VK_SRC/valkey-server" --bind 127.0.0.1 --protected-mode yes --port "$port" $extra \
      --save "" --appendonly no --daemonize no --dir "$RUNDIR/$port" \
      --logfile "$RUNDIR/$port/server.log" --pidfile "$RUNDIR/$port/pid" "$@" >/dev/null 2>&1 &
    for i in $(seq 1 100); do "$VK_SRC/valkey-cli" -p "$port" ping 2>/dev/null | grep -q PONG && exit 0; sleep 0.1; done
    echo "server on $port did not start" >&2; exit 1 ;;
  stop)
    "$VK_SRC/valkey-cli" -p "$port" shutdown nosave >/dev/null 2>&1
    sleep 0.3
    [ -f "$RUNDIR/$port/pid" ] && kill "$(cat "$RUNDIR/$port/pid")" 2>/dev/null
    exit 0 ;;
esac
