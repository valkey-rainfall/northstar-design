#!/bin/bash
# Phase 8 (linrep): run N histories against one server config and check each one, with replica readers.
# Usage: run_matrix8.sh <mode lanes|baseline> <port> <count> <seconds> <tag> [extra server args]
# Env: REPLICA_PORT (a replica of <port>, started by the caller), REPLICA_READERS (default 3 when REPLICA_PORT),
#      REPLICA_WAIT_WRITERS (default 2 when REPLICA_PORT), PIPELINE_ODD/PIPELINE_EVEN (default 0 / 4), RUNDIR, VK_SRC.
# Histories alternate: odd = PIPELINE_ODD, even = PIPELINE_EVEN (8 primary clients).
# Writes <RUNDIR>/<tag>/hNN.jsonl (kept only when FAIL), hNN.meta, hNN.check, hNN.drv and summary.txt.
set -u
D=$(cd "$(dirname "$0")" && pwd)
RUNDIR=${RUNDIR:-${WORK}/run-linearize}
mode=$1; port=$2; count=$3; secs=$4; tag=$5; shift 5
out=$RUNDIR/$tag
mkdir -p "$out"
RP=${REPLICA_PORT:-}
RR=${REPLICA_READERS:-3}; RW=${REPLICA_WAIT_WRITERS:-2}
PO=${PIPELINE_ODD:-0}; PE=${PIPELINE_EVEN:-4}
"$D/server.sh" start "$port" "$mode" "$@" || exit 3
if [ -n "$RP" ]; then "${VK_SRC}/valkey-cli" -p "$port" wait 1 10000 | grep -q 1 || { echo "replica not attached" >&2; exit 4; }; fi
echo "# tag=$tag mode=$mode port=$port replica=${RP:-none} readers=$RR wait_writers=$RW count=$count secs=$secs extra=$*" > "$out/summary.txt"
echo "# n pipeline ops errors verdict lane_entries lane_phases barriers fp_reads fp_writes snap_mgets repl_snap_reads repl_waited repl_acct_reads primary_snap_writes repl_parallel_applied repl_apply_phases repl_lane_barriers repl_lane_demoted" >> "$out/summary.txt"
pass=0; fail=0
for n in $(seq 1 "$count"); do
  pl=$PO; [ $((n % 2)) -eq 0 ] && pl=$PE
  h=$out/h$(printf %02d "$n")
  python3 "$D/driver.py" --port "$port" --seconds "$secs" --clients 8 --pipeline "$pl" --seed "$n" --out "$h.jsonl" \
    ${RP:+--replica-port $RP --replica-readers $RR --replica-wait-writers $RW} > "$h.drv" 2>&1 || { echo "$n driver-error" >> "$out/summary.txt"; cat "$h.drv"; continue; }
  python3 "$D/checker.py" "$h.jsonl" > "$h.check" 2>&1
  v=$(grep -o "VERDICT .*" "$h.check" | awk '{print $2}')
  [ "$v" = PASS ] && pass=$((pass+1)) || fail=$((fail+1))
  eng=$(python3 -c "import json,sys; m=json.load(open('$h.meta')); e=m['engagement']; r=m.get('replica_engagement',{}); print(m['ops'], m['resp_errors'], e['fastpath_write_lane_entries'], e['fastpath_write_lane_phases'], e['fastpath_write_barriers'], e['fastpath_reads'], e['fastpath_writes'], r.get('repl_parallel_applied',0), r.get('repl_apply_phases',0), r.get('repl_lane_barriers',0), r.get('repl_lane_demoted',0))")
  set -- $eng
  chk=$(head -1 "$h.check" | tr ' ' '\n' | awk -F= '/^(mgets|replica_snap_reads|replica_waited_reads|replica_account_reads|primary_snap_writes)=/{printf "%s ", $2}')
  if [ "$mode" = lanes ] && { [ "$3" -le 0 ] || [ "$6" -le 0 ]; }; then v="$v-NOENGAGE"; fail=$((fail+1)); pass=$((pass-1)); fi
  echo "$n $pl $1 $2 $v $3 $4 $5 $6 $7 $chk $8 $9 ${10} ${11}" >> "$out/summary.txt"
  [ "$v" = PASS ] && rm -f "$h.jsonl"
done
echo "# pass=$pass fail=$fail" >> "$out/summary.txt"
"$D/server.sh" stop "$port"
cat "$out/summary.txt"
