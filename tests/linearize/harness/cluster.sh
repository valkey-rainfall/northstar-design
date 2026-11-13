#!/bin/bash
# Phase 8 (linrep): a 3-node local cluster with write lanes, bound to 127.0.0.1, all ports in one range.
# Usage: cluster.sh start <base_port> <mode lanes|baseline>     nodes on base..base+2, bus ports base+10..base+12
#        cluster.sh stop  <base_port>
# Env: VK_SRC, RUNDIR, CORES (passed to server.sh)
set -u
D=$(cd "$(dirname "$0")" && pwd)
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
op=$1; base=$2; shift 2
CLI="${VK_SRC}/valkey-cli"
case "$op" in
  start)
    mode=$1
    for i in 0 1 2; do
      p=$((base + i))
      rm -rf "$RUNDIR/$p"; mkdir -p "$RUNDIR/$p"
      "$D/server.sh" start "$p" "$mode" --cluster-enabled yes --cluster-port $((base + 10 + i)) \
        --cluster-config-file nodes.conf --cluster-node-timeout 5000 || exit 3
    done
    "$CLI" -p "$base" cluster addslotsrange 0 5460 >/dev/null
    "$CLI" -p $((base + 1)) cluster addslotsrange 5461 10922 >/dev/null
    "$CLI" -p $((base + 2)) cluster addslotsrange 10923 16383 >/dev/null
    "$CLI" -p "$base" cluster meet 127.0.0.1 $((base + 1)) $((base + 11)) >/dev/null
    "$CLI" -p "$base" cluster meet 127.0.0.1 $((base + 2)) $((base + 12)) >/dev/null
    for n in $(seq 1 200); do
      ok=1
      for i in 0 1 2; do "$CLI" -p $((base + i)) cluster info 2>/dev/null | grep -q "cluster_state:ok" || ok=0; done
      [ $ok = 1 ] && { "$CLI" -p "$base" cluster nodes; exit 0; }
      sleep 0.1
    done
    echo "cluster did not converge" >&2; exit 4 ;;
  stop)
    for i in 0 1 2; do "$D/server.sh" stop $((base + i)); done ;;
esac
