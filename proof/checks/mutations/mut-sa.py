#!/usr/bin/env python3
# Mutation S-a (STREAM order S): main executes the first two entries of every client run of two or
# more entries in swapped order (e[from+1] before e[from]). Replies stay at their entries, so only the
# execution order inside one client's run changes. Run from the root of a northstar/proof-checks tree.
import sys

p = "src/fastpath.c"
s = open(p).read()
old = """    while (j < b->count && b->e[j].c == cl && j - from < max) {
        fpExecute(ec, b, &b->e[j]);
        j++;
    }
    c->ei = j;
"""
new = """    int len = 0;
    while (from + len < b->count && b->e[from + len].c == cl && len < max) len++;
    while (j < from + len) {
        int k = j;
        if (len >= 2 && j == from) k = from + 1; /* MUTATION S-a: swap the first two entries of the run */
        else if (len >= 2 && j == from + 1) k = from;
        fpExecute(ec, b, &b->e[k]);
        j++;
    }
    c->ei = j;
"""
if s.count(old) != 1:
    sys.exit("mut-sa: anchor not found once")
open(p, "w").write(s.replace(old, new))
print("mut-sa applied")
