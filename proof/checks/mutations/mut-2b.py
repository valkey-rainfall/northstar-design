#!/usr/bin/env python3
# Mutation m2b: the lane of a keyed entry is off by one, so every lane runs the entries of the next
# lane's partitions (the lane assignment and the partition ownership disagree).
f = "src/fastpath.c"
s = open(f).read()
old = "    return *shard % fp_nlanes;\n"
new = "    return (*shard + 1) % fp_nlanes; /* MUTATION m2b */\n"
assert s.count(old) == 1
open(f, "w").write(s.replace(old, new))
print("m2b applied")
