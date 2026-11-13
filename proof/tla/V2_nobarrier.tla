---------------------------- MODULE V2_nobarrier ----------------------------
EXTENDS Lanes
KeysInst == {"a", "b", "c", "d"}
ShardInst == [k \in KeysInst |-> CASE k = "a" -> 0 [] k = "b" -> 1 [] k = "c" -> 2 [] k = "d" -> 3]
\* NLanes 2: a,c on lane 0; b,d on lane 1. T is the harvest order (clients W,R,Z on thread 0; X,Y,Q on thread 1).
TInst == <<
  [cl |-> "W", op |-> "MSET",   keys |-> <<"a", "b">>, vals |-> <<"1", "1">>],
  [cl |-> "R", op |-> "MGET",   keys |-> <<"a", "b">>, vals |-> << >>],
  [cl |-> "W", op |-> "MSET",   keys |-> <<"a", "b">>, vals |-> <<"2", "2">>],
  [cl |-> "Z", op |-> "INCR",   keys |-> <<"d">>,      vals |-> << >>],
  [cl |-> "X", op |-> "DEL",    keys |-> <<"a", "b">>, vals |-> << >>],
  [cl |-> "R", op |-> "MGET",   keys |-> <<"b", "a">>, vals |-> << >>],
  [cl |-> "Y", op |-> "SET",    keys |-> <<"c">>,      vals |-> <<"7">>],
  [cl |-> "Y", op |-> "RENAME", keys |-> <<"c", "a">>, vals |-> << >>],
  [cl |-> "Z", op |-> "INCR",   keys |-> <<"d">>,      vals |-> << >>],
  [cl |-> "R", op |-> "GET",    keys |-> <<"a">>,      vals |-> << >>],
  [cl |-> "Q", op |-> "MSET",   keys |-> <<"b", "c">>, vals |-> <<"9", "9">>],
  [cl |-> "R", op |-> "MGET",   keys |-> <<"a", "b", "c", "d">>, vals |-> << >>]
>>
====================================================================
