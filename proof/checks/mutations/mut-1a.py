#!/usr/bin/env python3
# Mutation m1a: serve main-path clients and the cluster bus BEFORE the batches run (opens the window).
f = "src/staged_loop.c"
s = open(f).read()
old = """    int stream = stagedStreamEligible();
    if (stream) {"""
new = """    if (ae_ready) { /* MUTATION m1a: main-path clients and the cluster bus before the batches */
        aeProcessEvents(el, AE_FILE_EVENTS | AE_DONT_WAIT);
        ae_ready = 0;
    }
    int stream = stagedStreamEligible();
    if (stream) {"""
assert s.count(old) == 1
open(f, "w").write(s.replace(old, new))
print("m1a applied")
