---------------------------- MODULE MC2 ----------------------------
EXTENDS Lanes
KeysInst == {"a", "b", "c", "d", "e"}
ShardInst == [k \in KeysInst |-> CASE k = "a" -> 0 [] k = "b" -> 1 [] k = "c" -> 2 [] k = "d" -> 3 [] k = "e" -> 4]
\* NLanes 3: a,d on lane 0; b,e on lane 1; c on lane 2. Two barriers (RENAME across lanes, DEL across lanes).
\* Clients: P and R on thread 0, S, U and V on thread 1; T is their harvest order.
TInst == <<
  [cl |-> "P", op |-> "INCR",   keys |-> <<"d">>,                vals |-> << >>],
  [cl |-> "P", op |-> "MSET",   keys |-> <<"a", "b", "c">>,      vals |-> <<"1", "1", "1">>],
  [cl |-> "R", op |-> "MGET",   keys |-> <<"c", "a", "b">>,      vals |-> << >>],
  [cl |-> "R", op |-> "INCR",   keys |-> <<"d">>,                vals |-> << >>],
  [cl |-> "P", op |-> "RENAME", keys |-> <<"a", "e">>,           vals |-> << >>],
  [cl |-> "R", op |-> "MGET",   keys |-> <<"a", "e">>,           vals |-> << >>],
  [cl |-> "S", op |-> "MSET",   keys |-> <<"a", "c">>,           vals |-> <<"2", "2">>],
  [cl |-> "U", op |-> "GET",    keys |-> <<"b">>,                vals |-> << >>],
  [cl |-> "U", op |-> "MGET",   keys |-> <<"a", "b", "c">>,      vals |-> << >>],
  [cl |-> "V", op |-> "DEL",    keys |-> <<"b", "c">>,           vals |-> << >>],
  [cl |-> "V", op |-> "INCR",   keys |-> <<"d">>,                vals |-> << >>],
  [cl |-> "U", op |-> "MSET",   keys |-> <<"e", "a">>,           vals |-> <<"3", "3">>],
  [cl |-> "S", op |-> "MGET",   keys |-> <<"a", "b", "c", "e">>, vals |-> << >>],
  [cl |-> "V", op |-> "GET",    keys |-> <<"d">>,                vals |-> << >>]
>>
====================================================================
