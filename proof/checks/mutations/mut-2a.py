#!/usr/bin/env python3
# Mutation m2a (the audit's m2): fpKeysShard ignores the partition of every key after the first, so a
# multi-key command whose keys are in two partitions runs on the first key's lane.
f = "src/fastpath.c"
s = open(f).read()
old = """        if (i == 0) {
            shard = s;
        } else if (s != shard) {
            shard = -1;
            break;
        }
"""
new = """        if (i == 0) {
            shard = s; /* MUTATION m2a: the other keys' partitions are not compared */
        }
"""
assert s.count(old) == 1
open(f, "w").write(s.replace(old, new))
print("m2a applied")
