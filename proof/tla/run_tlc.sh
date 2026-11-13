#!/bin/sh
# Generate the TLC configs (correct design + 4 broken variants) and run TLC on each.
# Usage: sh run_tlc.sh /path/to/tla2tools.jar [cores]   (writes tlc-<name>.log next to the specs)
set -e
JAR="$1"
CORES="${2:-12,13}"
cd "$(dirname "$0")"
mk() { # mk <instance MC1|MC2> <nlanes> <name> <4 flags>
  inst="$1"; nl="$2"; name="$3"
  printf 'SPECIFICATION Spec\nINVARIANT SerialEquivalent\nCONSTANTS\n  Keys <- KeysInst\n  Shard <- ShardInst\n  T <- TInst\n  NLanes = %s\n  NIL = NIL\n  ReverseLane = %s\n  NoBarrierCross = %s\n  SplitCrossSeg = %s\n  StaleBarrier = %s\n' "$nl" "$4" "$5" "$6" "$7" > "$name.cfg"
  if [ "$name" != "$inst" ]; then sed "s/MODULE $inst/MODULE $name/" "$inst.tla" > "$name.tla"; fi
}
mk MC1 2 MC1 FALSE FALSE FALSE FALSE
mk MC1 2 V1_reverse TRUE FALSE FALSE FALSE
mk MC1 2 V2_nobarrier FALSE TRUE FALSE FALSE
mk MC1 2 V5_splitseg FALSE FALSE TRUE FALSE
mk MC1 2 V4_stale FALSE FALSE FALSE TRUE
mk MC2 3 MC2 FALSE FALSE FALSE FALSE
mk MC2 3 MC2_V1_reverse TRUE FALSE FALSE FALSE
mk MC2 3 MC2_V2_nobarrier FALSE TRUE FALSE FALSE
mk MC2 3 MC2_V5_splitseg FALSE FALSE TRUE FALSE
mk MC2 3 MC2_V4_stale FALSE FALSE FALSE TRUE
for n in MC1 V1_reverse V2_nobarrier V5_splitseg V4_stale MC2 MC2_V1_reverse MC2_V2_nobarrier MC2_V5_splitseg MC2_V4_stale; do
  echo "== $n"
  timeout 600 taskset -c "$CORES" java -XX:+UseSerialGC -Xmx1g -cp "$JAR" tlc2.TLC -workers 2 -deadlock -config "$n.cfg" "$n.tla" > "tlc-$n.log" 2>&1 || true
  grep -E "Model checking completed|Error:|Invariant SerialEquivalent is violated|states generated|distinct states" "tlc-$n.log" | head -5
done
rm -rf states
