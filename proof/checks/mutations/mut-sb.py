#!/usr/bin/env python3
# Mutation S-b (STREAM publish): main publishes a run (release store of b->executed up to the run's
# end) BEFORE it executes the run, instead of after, so a STREAM worker may deliver the run's replies
# before its entries ran. Run from the root of a northstar/proof-checks tree.
import sys

p = "src/fastpath.c"
s = open(p).read()
old = """                int before = cur[i].ei;
                fpStreamExecRun(ecs[i], b, &cur[i], run_window - w);
"""
new = """                int before = cur[i].ei;
                { /* MUTATION S-b: publish the run before it runs */
                    int end = before, lim = run_window - w;
                    while (end < b->count && b->e[end].c == b->e[before].c && end - before < lim) end++;
                    fpStreamPublish(b, end);
                }
                fpStreamExecRun(ecs[i], b, &cur[i], run_window - w);
"""
if s.count(old) != 1:
    sys.exit("mut-sb: anchor not found once")
open(p, "w").write(s.replace(old, new))
print("mut-sb applied")
