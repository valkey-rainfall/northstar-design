------------------------------- MODULE Lanes -------------------------------
(* The proof-of-concept write-lane plan (src/fastpath.c fpExecuteWithLanes / fastpathStagedWriteLane at HEAD
   1fb18b7d), as an abstract machine for TLC.

   One iteration. T is the harvest order (thread-major), a sequence of command records. Each entry is a
   lane entry, a split entry (MSET/MGET: one part per lane) or a barrier. Barriers cut T into segments;
   segment j runs on the lanes (each lane in T order, steps of different lanes interleaved freely by TLC),
   then barrier j runs alone. The invariant: when everything ran, the state and every reply equal the serial
   execution of T. Broken variants are CONSTANT flags. *)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS Keys, Shard, NLanes, T, NIL,
          ReverseLane,     \* V1: the highest lane runs its entries in reverse T order
          NoBarrierCross,  \* V2: a cross-lane command runs on the lane of its first key
          SplitCrossSeg,   \* V5: the parts of a split entry not on the first key's lane run one segment later
          StaleBarrier     \* V4: missing happens-before: a barrier may read the state before the last lane phase

Lanes == 0 .. NLanes - 1
N == Len(T)
Lane(k) == Shard[k] % NLanes
Range(s) == {s[i] : i \in 1 .. Len(s)}
LanesOf(e) == {Lane(k) : k \in Range(e.keys)}

Class(i) == LET e == T[i] IN
  IF Cardinality(LanesOf(e)) = 1 THEN "lane"
  ELSE IF e.op \in {"MSET", "MGET"} THEN "split"
  ELSE IF NoBarrierCross THEN "lane" ELSE "barrier"

FirstLane(i) == Lane(T[i].keys[1])

RECURSIVE Seg(_)
Seg(i) == IF i = 1 THEN 0 ELSE Seg(i - 1) + (IF Class(i - 1) = "barrier" THEN 1 ELSE 0)

NBarriers == Cardinality({i \in 1 .. N : Class(i) = "barrier"})
BarrierOf(j) == CHOOSE i \in 1 .. N : Class(i) = "barrier" /\ Seg(i) = j
MaxPhase == NBarriers + (IF SplitCrossSeg THEN 1 ELSE 0)

\* The phase in which entry i's part on lane l runs
PhaseOf(i, l) == Seg(i) + (IF SplitCrossSeg /\ Class(i) = "split" /\ l # FirstLane(i) THEN 1 ELSE 0)

OnLane(i, l) == Class(i) # "barrier" /\
  (IF Class(i) = "split" THEN l \in LanesOf(T[i]) ELSE (IF NoBarrierCross /\ Cardinality(LanesOf(T[i])) > 1 THEN l = FirstLane(i) ELSE l \in LanesOf(T[i])))

\* Per-key steps of entry i on lane l: [e: entry index, kind, kidx: key position]
KeyIdx(i, l) == IF Class(i) = "split" THEN [x \in 1 .. Len(T[i].keys) |-> x] ELSE [x \in 1 .. Len(T[i].keys) |-> x]
StepsOf(i, l) ==
  LET e == T[i]
      idx == [x \in 1 .. Len(e.keys) |-> x]
      keep == SelectSeq(idx, LAMBDA x : Class(i) # "split" \/ Lane(e.keys[x]) = l)
  IN IF e.op = "RENAME" THEN << [e |-> i, kind |-> "rn_r", kidx |-> 1], [e |-> i, kind |-> "rn_w", kidx |-> 2], [e |-> i, kind |-> "rn_d", kidx |-> 1] >>
     ELSE [x \in 1 .. Len(keep) |-> [e |-> i, kind |-> (IF e.op \in {"SET", "MSET"} THEN "w" ELSE IF e.op \in {"GET", "MGET"} THEN "r" ELSE IF e.op = "INCR" THEN "incr" ELSE "d"), kidx |-> keep[x]]]

RECURSIVE Concat(_)
Concat(ss) == IF Len(ss) = 0 THEN << >> ELSE Head(ss) \o Concat(Tail(ss))

EntriesOn(j, l) == LET s == SelectSeq([i \in 1 .. N |-> i], LAMBDA i : OnLane(i, l) /\ PhaseOf(i, l) = j)
                   IN IF ReverseLane /\ l = NLanes - 1 THEN [x \in 1 .. Len(s) |-> s[Len(s) + 1 - x]] ELSE s
LaneSteps(j, l) == Concat([x \in 1 .. Len(EntriesOn(j, l)) |-> StepsOf(EntriesOn(j, l)[x], l)])

VARIABLES kv, kvOld, phase, pc, out, tmp

Init == kv = [k \in Keys |-> NIL] /\ kvOld = kv /\ phase = 0 /\ pc = [l \in Lanes |-> 1]
        /\ out = [i \in 1 .. N |-> [x \in 1 .. Len(T[i].keys) |-> NIL]] /\ tmp = [i \in 1 .. N |-> NIL]

Val(i, x) == T[i].vals[x]

DoStep(st) ==
  LET i == st.e  k == T[i].keys[st.kidx] IN
  CASE st.kind = "w" -> kv' = [kv EXCEPT ![k] = Val(i, st.kidx)] /\ UNCHANGED <<out, tmp>>
    [] st.kind = "r" -> out' = [out EXCEPT ![i][st.kidx] = kv[k]] /\ UNCHANGED <<kv, tmp>>
    [] st.kind = "incr" -> LET v == IF kv[k] = NIL THEN 1 ELSE kv[k] + 1 IN
                            kv' = [kv EXCEPT ![k] = v] /\ out' = [out EXCEPT ![i][st.kidx] = v] /\ UNCHANGED tmp
    [] st.kind = "d" -> kv' = [kv EXCEPT ![k] = NIL] /\ out' = [out EXCEPT ![i][st.kidx] = (IF kv[k] = NIL THEN 0 ELSE 1)] /\ UNCHANGED tmp
    [] st.kind = "rn_r" -> tmp' = [tmp EXCEPT ![i] = kv[k]] /\ UNCHANGED <<kv, out>>
    [] st.kind = "rn_w" -> kv' = (IF tmp[i] = NIL THEN kv ELSE [kv EXCEPT ![k] = tmp[i]]) /\ UNCHANGED <<out, tmp>>
    [] st.kind = "rn_d" -> kv' = (IF tmp[i] = NIL THEN kv ELSE [kv EXCEPT ![k] = NIL]) /\ out' = [out EXCEPT ![i][1] = (IF tmp[i] = NIL THEN "ERR" ELSE "OK")] /\ UNCHANGED tmp

LaneStep(l) == phase <= MaxPhase /\ pc[l] <= Len(LaneSteps(phase, l))
  /\ DoStep(LaneSteps(phase, l)[pc[l]]) /\ pc' = [pc EXCEPT ![l] = pc[l] + 1] /\ UNCHANGED <<phase, kvOld>>

LanesDone == \A l \in Lanes : pc[l] > Len(LaneSteps(phase, l))

\* Whole-command semantics for barriers and the serial reference: returns [kv |-> ..., rep |-> ...]
Apply(st, e) ==
  LET ks == e.keys IN
  CASE e.op = "SET" -> [kv |-> [st EXCEPT ![ks[1]] = e.vals[1]], rep |-> "OK"]
    [] e.op = "GET" -> [kv |-> st, rep |-> << st[ks[1]] >>]
    [] e.op = "INCR" -> LET v == IF st[ks[1]] = NIL THEN 1 ELSE st[ks[1]] + 1 IN [kv |-> [st EXCEPT ![ks[1]] = v], rep |-> v]
    [] e.op = "DEL" -> [kv |-> [k \in Keys |-> IF k \in Range(ks) THEN NIL ELSE st[k]],
                        rep |-> Cardinality({k \in Range(ks) : st[k] # NIL})]
    [] e.op = "MSET" -> [kv |-> [k \in Keys |-> IF k \in Range(ks) THEN e.vals[CHOOSE x \in 1 .. Len(ks) : ks[x] = k /\ \A y \in x + 1 .. Len(ks) : ks[y] # k] ELSE st[k]], rep |-> "OK"]
    [] e.op = "MGET" -> [kv |-> st, rep |-> [x \in 1 .. Len(ks) |-> st[ks[x]]]]
    [] e.op = "RENAME" -> IF st[ks[1]] = NIL THEN [kv |-> st, rep |-> "ERR"]
                          ELSE [kv |-> [[st EXCEPT ![ks[2]] = st[ks[1]]] EXCEPT ![ks[1]] = NIL], rep |-> "OK"]

Reply(i) == LET e == T[i] IN
  CASE e.op \in {"SET", "MSET"} -> "OK"
    [] e.op = "GET" -> out[i]
    [] e.op = "MGET" -> out[i]
    [] e.op = "INCR" -> out[i][1]
    [] e.op = "DEL" -> Cardinality({x \in 1 .. Len(e.keys) : out[i][x] = 1})
    [] e.op = "RENAME" -> out[i][1]

VARIABLES brep
vars == <<kv, kvOld, phase, pc, out, tmp, brep>>

InitAll == Init /\ brep = [i \in 1 .. N |-> NIL]

Barrier == phase < NBarriers /\ LanesDone /\
  LET i == BarrierOf(phase)
      views == IF StaleBarrier THEN {kv, kvOld} ELSE {kv}
  IN \E v \in views :
       LET r == Apply(v, T[i]) IN
       \* a stale view: the barrier's writes land on top of the real state (lost update of the lane phase)
       kv' = [k \in Keys |-> IF r.kv[k] # v[k] THEN r.kv[k] ELSE kv[k]]
       /\ brep' = [brep EXCEPT ![i] = r.rep]
  /\ kvOld' = kv' /\ phase' = phase + 1 /\ pc' = [l \in Lanes |-> 1] /\ UNCHANGED <<out, tmp>>

PhaseWithoutBarrier == phase >= NBarriers /\ phase < MaxPhase /\ LanesDone
  /\ kvOld' = kv /\ phase' = phase + 1 /\ pc' = [l \in Lanes |-> 1] /\ UNCHANGED <<kv, out, tmp, brep>>

StartPhase0 == TRUE
Next == (\E l \in Lanes : LaneStep(l) /\ UNCHANGED brep) \/ Barrier \/ PhaseWithoutBarrier

Spec == InitAll /\ [][Next]_vars

\* Serial reference over T
RECURSIVE Serial(_, _, _)
Serial(i, st, reps) == IF i > N THEN [kv |-> st, rep |-> reps]
                       ELSE LET r == Apply(st, T[i]) IN Serial(i + 1, r.kv, Append(reps, r.rep))
Ref == Serial(1, [k \in Keys |-> NIL], << >>)

Done == phase = MaxPhase /\ LanesDone
RepOf(i) == IF Class(i) = "barrier" THEN brep[i] ELSE Reply(i)

\* G3/G4/G5/G6 inside the iteration: the result equals the serial execution of T (T itself respects every
\* client's order, so G2 holds by construction; G1 is the delivery order, not modelled here).
SerialEquivalent == Done => (kv = Ref.kv /\ \A i \in 1 .. N : RepOf(i) = Ref.rep[i])

=============================================================================
