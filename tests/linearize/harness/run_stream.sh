#!/bin/bash
# Run N linearize histories against one server and record the STREAM-path coverage of each.
# Like run_matrix.sh, with the client count, pipeline depth and seed base set by the caller.
# Usage: run_stream.sh <mode lanes|baseline> <port> <count> <seconds> <tag> [extra server args]
# Env: CLIENTS (default 16), PIPES (space-separated pipeline depths, cycled; default "0 4"),
#      SEED0 (seed of history 1 minus 1; default 0), RUNDIR, VK_SRC, CORES (see server.sh).
# Needs a STAGED_CHECKS build for the staged_check_stream_* columns (0 otherwise).
# Writes <RUNDIR>/<tag>/hNN.{meta,check,drv} and <RUNDIR>/<tag>/summary.txt; keeps hNN.jsonl only on FAIL.
set -u
D=$(cd "$(dirname "$0")" && pwd)
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
CLIENTS=${CLIENTS:-16}
PIPES=${PIPES:-"0 4"}
SEED0=${SEED0:-0}
mode=$1; port=$2; count=$3; secs=$4; tag=$5; shift 5
out=$RUNDIR/$tag
mkdir -p "$out"
"$D/server.sh" start "$port" "$mode" "$@" || exit 3
read -r -a pipes <<< "$PIPES"
echo "# tag=$tag mode=$mode port=$port count=$count secs=$secs clients=$CLIENTS pipes=$PIPES seed0=$SEED0 extra=$*" > "$out/summary.txt"
echo "# n seed pipeline ops errors verdict lane_entries lane_phases stream_phases stream_execs stream_multi stream_runs stream_entries stream_cuts" >> "$out/summary.txt"
pass=0; fail=0
for n in $(seq 1 "$count"); do
  pl=${pipes[$(( (n - 1) % ${#pipes[@]} ))]}
  seed=$((SEED0 + n))
  h=$out/h$(printf %02d "$n")
  if ! python3 "$D/driver.py" --port "$port" --seconds "$secs" --clients "$CLIENTS" --pipeline "$pl" --seed "$seed" \
      --out "$h.jsonl" > "$h.drv" 2>&1; then
    echo "$n $seed $pl driver-error" >> "$out/summary.txt"; fail=$((fail+1)); tail -3 "$h.drv"; continue
  fi
  timeout "${CHECK_TIMEOUT:-600}" python3 "$D/checker.py" "$h.jsonl" > "$h.check" 2>&1 || echo "checker exit $? (124 = timeout)" >> "$h.check"
  v=$(grep -o "VERDICT .*" "$h.check" | awk '{print $2}')
  [ -n "$v" ] || v=NO-VERDICT
  [ "$v" = PASS ] && pass=$((pass+1)) || fail=$((fail+1))
  eng=$(python3 -c "import json; m=json.load(open('$h.meta')); e=m['engagement']; print(m['ops'], m['resp_errors'], *[e.get(f, 0) for f in ('fastpath_write_lane_entries', 'fastpath_write_lane_phases', 'staged_stream_phases', 'staged_check_stream_execs', 'staged_check_stream_multi', 'staged_check_stream_runs', 'staged_check_stream_entries', 'staged_check_stream_cuts')])")
  echo "$n $seed $pl $eng $v" | awk '{v=$NF; $NF=""; print $1, $2, $3, $4, $5, v, $6, $7, $8, $9, $10, $11, $12, $13}' >> "$out/summary.txt"
  [ "$v" = PASS ] && rm -f "$h.jsonl"
done
echo "# pass=$pass fail=$fail" >> "$out/summary.txt"
"$D/server.sh" stop "$port"
cat "$out/summary.txt"
