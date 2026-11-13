P=$(dirname "$0")/probe.py
port=24140
for spec in "tcp 0" "tls 0" "merge 0" "merge 2" "merge-tls 2" "tls 2" "ep2 2" "ep2-tls 2"; do
  set -- $spec
  python3 $P ./src/valkey-server $PWD/tests/tls $1 $port 8 300 $2 > ${OUT:-.}/$1-ahead$2.log 2>&1; echo "$1 ahead=$2 rc=$?"
  grep -v "^round" ${OUT:-.}/$1-ahead$2.log | cut -c1-360
  port=$((port+1))
done
