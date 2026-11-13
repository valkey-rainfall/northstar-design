#!/bin/bash
# Run N histories against one server config and check each one.
# Usage: run_matrix.sh <mode lanes|baseline> <port> <count> <seconds> <tag> [extra server args]
# Histories alternate: odd = not pipelined (8 clients), even = pipelined 4 (8 clients).
# Writes <RUNDIR>/<tag>/hNN.jsonl, hNN.meta, hNN.check and a summary table <RUNDIR>/<tag>/summary.txt.
set -u
D=$(cd "$(dirname "$0")" && pwd)
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
mode=$1; port=$2; count=$3; secs=$4; tag=$5; shift 5
out=$RUNDIR/$tag
mkdir -p "$out"
"$D/server.sh" start "$port" "$mode" "$@" || exit 3
echo "# tag=$tag mode=$mode port=$port count=$count secs=$secs extra=$*" > "$out/summary.txt"
echo "# n pipeline ops errors verdict lane_entries lane_phases barriers fp_reads fp_writes speculated" >> "$out/summary.txt"
pass=0; fail=0
for n in $(seq 1 "$count"); do
  pl=0; [ $((n % 2)) -eq 0 ] && pl=4
  h=$out/h$(printf %02d "$n")
  python3 "$D/driver.py" --port "$port" --seconds "$secs" --clients 8 --pipeline $pl --seed "$n" --out "$h.jsonl" \
    ${REPLICA_PORT:+--replica-port $REPLICA_PORT} > "$h.drv" 2>&1 || { echo "$n driver-error" >> "$out/summary.txt"; cat "$h.drv"; continue; }
  python3 "$D/checker.py" "$h.jsonl" > "$h.check" 2>&1
  v=$(grep -o "VERDICT .*" "$h.check" | awk '{print $2}')
  [ "$v" = PASS ] && pass=$((pass+1)) || fail=$((fail+1))
  eng=$(python3 -c "import json,sys; m=json.load(open('$h.meta')); e=m['engagement']; print(m['ops'], m['resp_errors'], e['fastpath_write_lane_entries'], e['fastpath_write_lane_phases'], e['fastpath_write_barriers'], e['fastpath_reads'], e['fastpath_writes'], e['fastpath_speculated'])")
  set -- $eng
  if [ "$mode" = lanes ] && { [ "$3" -le 0 ] || [ "$6" -le 0 ]; }; then v="$v-NOENGAGE"; fail=$((fail+1)); pass=$((pass-1)); fi
  echo "$n $pl $1 $2 $v $3 $4 $5 $6 $7 $8" >> "$out/summary.txt"
  # histories are large (tens of MB): keep only the failing ones, plus meta and check output for all
  [ "$v" = PASS ] && rm -f "$h.jsonl"
done
echo "# pass=$pass fail=$fail" >> "$out/summary.txt"
"$D/server.sh" stop "$port"
cat "$out/summary.txt"
