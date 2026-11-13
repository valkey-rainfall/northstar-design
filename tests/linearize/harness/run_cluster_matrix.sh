#!/bin/bash
# Phase 8 (linrep): N histories against a running 3-node cluster (cluster.sh start <base> lanes), rotating the
# target node: history n uses node n%3 with a hash tag whose slot that node owns, and CROSSSLOT probes against
# a tag of another node's slot. Odd = not pipelined, even = pipelined 4.
# Usage: run_cluster_matrix.sh <base_port> <count> <seconds> <tag>
set -u
D=$(cd "$(dirname "$0")" && pwd)
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
base=$1; count=$2; secs=$3; tag=$4
out=$RUNDIR/$tag; mkdir -p "$out"
TAGS=(b c a)   # {b} -> slot 3300 (node 0: 0-5460), {c} -> 7365 (node 1: 5461-10922), {a} -> 15495 (node 2: 10923-16383)
echo "# tag=$tag cluster base=$base count=$count secs=$secs" > "$out/summary.txt"
echo "# n node hashtag pipeline ops errors verdict lane_entries lane_phases barriers fp_reads fp_writes serial_segments snap_mgets primary_snap_writes crossslot_probes" >> "$out/summary.txt"
pass=0; fail=0
for n in $(seq 1 "$count"); do
  pl=0; [ $((n % 2)) -eq 0 ] && pl=4
  i=$((n % 3)); port=$((base + i)); ht=${TAGS[$i]}; xt=${TAGS[$(( (i + 1) % 3 ))]}
  h=$out/h$(printf %02d "$n")
  python3 "$D/driver.py" --port "$port" --seconds "$secs" --clients 8 --pipeline "$pl" --seed "$n" --out "$h.jsonl" \
    --hashtag "$ht" --cross-slot-tag "$xt" --cross-slot-clients 1 > "$h.drv" 2>&1 || { echo "$n driver-error" >> "$out/summary.txt"; cat "$h.drv"; continue; }
  python3 "$D/checker.py" "$h.jsonl" > "$h.check" 2>&1
  v=$(grep -o "VERDICT .*" "$h.check" | awk '{print $2}')
  [ "$v" = PASS ] && pass=$((pass+1)) || fail=$((fail+1))
  eng=$(python3 -c "import json; m=json.load(open('$h.meta')); e=m['engagement']; print(m['ops'], m['resp_errors'], e['fastpath_write_lane_entries'], e['fastpath_write_lane_phases'], e['fastpath_write_barriers'], e['fastpath_reads'], e['fastpath_writes'], e['fastpath_write_serial_segments'])")
  set -- $eng
  chk=$(head -1 "$h.check" | tr ' ' '\n' | awk -F= '/^(mgets|primary_snap_writes|crossslot_probes)=/{printf "%s ", $2}')
  if [ "$3" -le 0 ] || [ "$6" -le 0 ]; then v="$v-NOENGAGE"; fail=$((fail+1)); pass=$((pass-1)); fi
  echo "$n $port $ht $pl $1 $2 $v $3 $4 $5 $6 $7 $8 $chk" >> "$out/summary.txt"
  [ "$v" = PASS ] && rm -f "$h.jsonl"
done
echo "# pass=$pass fail=$fail" >> "$out/summary.txt"
cat "$out/summary.txt"
