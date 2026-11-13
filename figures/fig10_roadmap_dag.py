# Figure 10 for the North Star design doc: the roadmap steps of section 10 as a
# dependency graph, left to right. graphviz dot computes the layered layout
# (crossings minimized, edges routed around nodes, "dot -Tplain"); matplotlib
# draws it with the palette (Okabe-Ito READ blue) and fonts (DejaVu Sans, 9 to
# 10.5 pt) of fig_timelines.py, plus a two-line legend under the graph.
# Solid arrow: "Depends on"; dashed arrow: "should land before". Step 11 (later
# options) has no dependency and is left out; the caption says so.
import os
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.path import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FILL = "#56B4E9"

NODES = {
    1: "Flags word split\n+ sanitizer job",
    2: "Keyspace partitions",
    3: "Basic phased loop",
    4: "Collector thread\n+ STREAM phase",
    5: "ACL evaluation\non IO threads",
    6: "Fast reads",
    7: "Replication throttling\n+ phased loop",
    8: "Write lanes\non a primary",
    9: "Parallel apply\non a replica",
    10: "Parallel table\nmaintenance",
    11: "Later options",
}
# "Depends on" edges of section 10, reduced to the direct ones: an edge A -> C is
# left out when A -> B -> C exists (2 -> 9 and 3 -> 9 go through 8).
DEPENDS = [(1, 3), (3, 4), (3, 6), (5, 6), (3, 7), (2, 8), (3, 8), (8, 9), (2, 10), (3, 10)]
BEFORE = [(7, 8)]  # dashed: lands with
RANKS = [[1], [3], [5, 2, 4, 7], [6, 10, 8], [9], [11]]

# --- layout by dot ---
lines = ["digraph roadmap {", "  rankdir=LR; splines=spline; nodesep=0.3; ranksep=0.8;",
         '  node [shape=box, fontname="DejaVu Sans", fontsize=10.5, margin="0.22,0.10"];']
for n, t in NODES.items():
    lines.append('  s%d [label="%d. %s"];' % (n, n, t.replace("\n", "\\n")))
for a, b in DEPENDS:
    lines.append("  s%d -> s%d;" % (a, b))
for a, b in BEFORE:
    lines.append("  s%d -> s%d [style=dashed];" % (a, b))
for r in RANKS:
    lines.append("  { rank=same; %s }" % " ".join("s%d;" % n for n in r))
# order inside a rank: invisible edges top to bottom
for r in RANKS:
    for a, b in zip(r, r[1:]):
        lines.append("  s%d -> s%d [style=invis];" % (a, b))
# step 11 has no dependency; an invisible edge keeps it in the last rank
lines.append("  s9 -> s11 [style=invis];")
lines.append("}")
dot_src = "\n".join(lines) + "\n"
open(os.path.join(HERE, "fig10_roadmap_dag.dot"), "w").write(dot_src)
plain = subprocess.run(["dot", "-Tplain"], input=dot_src, capture_output=True, text=True, check=True).stdout

nodes, edges = {}, []
for ln in plain.splitlines():
    f = ln.split()
    if f[0] == "node":
        nodes[int(f[1][1:])] = (float(f[2]), float(f[3]), float(f[4]), float(f[5]))
    elif f[0] == "edge":
        a, b, k = int(f[1][1:]), int(f[2][1:]), int(f[3])
        if (a, b) not in DEPENDS and (a, b) not in BEFORE:
            continue  # invisible ordering edges
        pts = [(float(f[4 + 2 * i]), float(f[5 + 2 * i])) for i in range(k)]
        edges.append((a, b, pts))
gw = max(x + w / 2 for x, y, w, h in nodes.values())
gh = max(y + h / 2 for x, y, w, h in nodes.values())

# --- draw ---
fig, ax = plt.subplots(figsize=(gw + 0.4, gh + 1.9), dpi=200)  # one dot inch = one figure inch
ax.set_xlim(-0.1, gw + 0.1)
ax.set_ylim(-1.35, gh + 0.4)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("Figure 10. Roadmap steps (section 10) and their direct dependencies, left to right", fontsize=10.5, loc="left")

for n, (x, y, w, h) in nodes.items():
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.0,rounding_size=0.08",
                                facecolor=FILL, edgecolor="black", linewidth=0.8))
    ax.text(x, y, "%d. %s" % (n, NODES[n]), ha="center", va="center", fontsize=9, linespacing=1.15)

dashed = set(BEFORE)
for a, b, pts in edges:
    # dot gives a cubic B-spline: p0, then groups of three control points
    verts = [pts[0]]
    codes = [Path.MOVETO]
    for i in range(1, len(pts), 3):
        verts += pts[i:i + 3]
        codes += [Path.CURVE4] * 3
    style = (0, (4, 3)) if (a, b) in dashed else "solid"
    ax.add_patch(FancyArrowPatch(path=Path(verts, codes), arrowstyle="-|>,head_length=4,head_width=2.5",
                                 color="black", linewidth=0.8, linestyle=style, shrinkA=0, shrinkB=0))

# legend, two lines under the graph
ly = -0.55
ax.add_patch(FancyArrowPatch((0.2, ly), (1.2, ly), arrowstyle="-|>,head_length=4,head_width=2.5", color="black", linewidth=0.8))
ax.text(1.35, ly, "solid arrow from A to B: B depends on A", va="center", fontsize=9)
ly = -1.0
ax.add_patch(FancyArrowPatch((0.2, ly), (1.2, ly), arrowstyle="-|>,head_length=4,head_width=2.5", color="black", linewidth=0.8, linestyle=(0, (4, 3))))
ax.text(1.35, ly, "dashed arrow from A to B: A lands with B", va="center", fontsize=9)

for ext in ("png", "svg"):
    fig.savefig(os.path.join(HERE, f"fig10_roadmap_dag.{ext}"), bbox_inches="tight")
print("ok")
