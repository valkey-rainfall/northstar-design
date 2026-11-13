#!/usr/bin/env python3
# Mutation m1b: classification ignores watched and blocked keys, so a write to an observed key becomes
# a lane entry instead of a barrier entry.
f = "src/fastpath.c"
s = open(f).read()
old = "    int checks = fp_check_blocked || fp_check_watched;\n"
new = "    int checks = 0; /* MUTATION m1b: observers ignored at classification */\n"
assert s.count(old) == 2
open(f, "w").write(s.replace(old, new))
print("m1b applied")
