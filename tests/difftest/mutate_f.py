#!/usr/bin/env python3
"""Apply one production mutation to src/fastpath.c of a worktree at F (f01d005ea) or PRFIX (argument:
m1..m4). Each mutation breaks one ordering rule the lanes rely on; FastpathDifftest must fail on each.
Phase 23b version of tests/difftest/mutate.py: m1 reverses the lane's collected run list (the lane
walk at F collects its entries first, then runs them); m2-m4 keep the Phase 6 anchors, which are
unchanged at F. Run from the worktree root; restore with git checkout src/fastpath.c."""
import sys

p = "src/fastpath.c"
s = open(p).read()
m = sys.argv[1]

def must(old, new):
    global s
    assert s.count(old) == 1, ("anchor not unique: " + old)
    s = s.replace(old, new)

if m == "m1":
    must("""    int use_prefetch = server.io_threads_lane_prefetch && L->nrun > 1;""",
         """    for (int i = 0, j = L->nrun - 1; i < j; i++, j--) { /* MUTATION m1: reversed lane order */
        cmdEntry *tmp = L->run[i];
        L->run[i] = L->run[j];
        L->run[j] = tmp;
    }
    int use_prefetch = server.io_threads_lane_prefetch && L->nrun > 1;""")
elif m == "m2":
    must("""        } else if (s != shard) {
            shard = -1;
            break;
        }
    }
    getKeysFreeResult(&result);
    return shard;""", """        } else if (0 && s != shard) { /* MUTATION m2: second key's shard ignored */
            shard = -1;
            break;
        }
    }
    getKeysFreeResult(&result);
    return shard;""")
elif m == "m3":
    must("""            total += fpRunSegment(pending, serial, use_prefetch);
            pending = 0;
            if (use_prefetch && s >= t->pf_barrier) fpPrefetchBarriers(t, s);
            struct fpBarrier *br = &t->barriers[s];
            client *ec = fpExecutor(tid);
            fpExecute(ec, br->b, br->e);
            ec->origin = NULL;
            clientSetUser(ec, DefaultUser, 0);
            total++;
            fp_stat_barriers++;""", """            if (use_prefetch && s >= t->pf_barrier) fpPrefetchBarriers(t, s);
            struct fpBarrier *br = &t->barriers[s];
            client *ec = fpExecutor(tid);
            fpExecute(ec, br->b, br->e); /* MUTATION m3: barrier before its segment */
            ec->origin = NULL;
            clientSetUser(ec, DefaultUser, 0);
            total++;
            fp_stat_barriers++;
            total += fpRunSegment(pending, serial, use_prefetch);
            pending = 0;""")
elif m == "m4":
    must("""        pt->e.lane = lanes[p];""", """        pt->e.lane = lanes[p];
        if (p > 0) pt->e.seg += 1; /* MUTATION m4: later parts in the next segment */""")
else:
    sys.exit("unknown mutation")
open(p, "w").write(s)
print("applied", m)
