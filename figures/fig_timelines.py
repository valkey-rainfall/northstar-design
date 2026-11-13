# Figures 3-7 and 9 for the North Star design doc: one loop iteration as a timeline,
# one row per thread, for the basic loop (4.1), fast reads (4.2), one lane
# phase (4.3), lane phases around a barrier entry (4.4) and STREAM (4.5).
# The five figures share the layout, colors and time scale so only the change
# stands out. Palette: Okabe-Ito (color-blind safe). Text is 9 pt or larger.
import os
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))

C = {
    "collect": "#BBBBBB",
    "READ": "#56B4E9",
    "WRITE": "#E69F00",
    "lane": "#009E73",
    "B": "#D55E00",
    "STREAM": "#CC79A7",
    "AOF": "#F0E442",
    "REPLY": "#0072B2",
    "cron": "#999999",
}
ROWS = ["main", "IO 1", "IO 2", "IO 3"]
Y = {r: 3 - i for i, r in enumerate(ROWS)}
# time columns (start, end): collect, READ, WRITE, AOF, REPLY, cron
T = {"collect": (0.0, 1.0), "READ": (1.0, 2.6), "WRITE": (2.6, 5.4), "AOF": (5.4, 6.1),
     "REPLY": (6.1, 7.5), "cron": (7.5, 8.4)}


def block(ax, row, x0, x1, color, label, fs=9.5, fc="black"):
    ax.add_patch(Rectangle((x0, Y[row] - 0.36), x1 - x0, 0.72, facecolor=color,
                           edgecolor="black", linewidth=0.6))
    ax.text((x0 + x1) / 2, Y[row], label, ha="center", va="center", fontsize=fs, color=fc)


MARKS = {}


def barrier(ax, x, kind):
    # collected per figure; drawn in save(), so a close and an open at the same
    # instant share one line and one label ("close / open")
    MARKS.setdefault(round(x, 3), []).append(kind)


def draw_barriers(ax):
    for x, kinds in sorted(MARKS.items()):
        ax.axvline(x, color="black", linewidth=0.9, linestyle=(0, (3, 2)), ymin=0.04, ymax=0.90)
        ax.text(x, 3.62, " / ".join(kinds), ha="center", va="bottom", fontsize=9, color="black")
    MARKS.clear()


def frame(title):
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=200)
    ax.set_xlim(-0.05, 8.5)
    ax.set_ylim(-0.95, 4.0)
    ax.set_yticks([Y[r] for r in ROWS])
    ax.set_yticklabels(ROWS, fontsize=10)
    ax.set_xticks([])
    for sp in ("top", "right", "bottom", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    # idle: a thin gray line for every row; blocks are drawn on top of it
    for r in ROWS:
        ax.plot([0, 8.4], [Y[r], Y[r]], color="#AAAAAA", linewidth=1.0, zorder=0)
    ax.annotate("time", xy=(8.45, -0.75), xytext=(7.4, -0.75), fontsize=9,
                arrowprops=dict(arrowstyle="->", lw=0.8), va="center")
    ax.text(-0.05, 3.62, "barrier:", ha="left", va="bottom", fontsize=9)
    ax.set_title(title, fontsize=10.5, loc="left")
    return fig, ax


def common(ax, read_label="READ", write_main=True):
    block(ax, "main", *T["collect"], C["collect"], "collect")
    for r in ROWS[1:]:
        block(ax, r, *T["READ"], C["READ"], read_label)
    block(ax, "main", *T["READ"], C["READ"], read_label)
    if write_main:
        block(ax, "main", *T["WRITE"], C["WRITE"], "WRITE: main executes every entry")
    block(ax, "main", *T["AOF"], C["AOF"], "AOF")
    for r in ROWS:
        block(ax, r, *T["REPLY"], C["REPLY"], "REPLY", fc="white")
    block(ax, "main", *T["cron"], C["cron"], "cron")
    barrier(ax, T["READ"][0], "open")
    barrier(ax, T["READ"][1], "close")
    barrier(ax, T["REPLY"][0], "open")
    barrier(ax, T["REPLY"][1], "close")


def save(fig, name):
    draw_barriers(fig.axes[0])
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(HERE, f"{name}.{ext}"), bbox_inches="tight")
    plt.close(fig)


# Figure 3: the basic loop (4.1)
fig, ax = frame("Figure 3. One iteration of the basic phased loop (4.1)")
common(ax)
save(fig, "fig3_loop_basic")

# Figure 4: fast reads answered inside READ (4.2)
fig, ax = frame("Figure 4. The same iteration with fast reads (4.2)")
common(ax, read_label="READ + fast reads")
save(fig, "fig4_loop_fastreads")

# Figure 5: WRITE as one lane phase on every thread (4.3)
fig, ax = frame("Figure 5. WRITE as one lane phase (4.3)")
common(ax, write_main=False)
for i, r in enumerate(ROWS):
    block(ax, r, *T["WRITE"], C["lane"], f"WRITE: lane {i}", fc="white")
barrier(ax, T["WRITE"][0], "open")
barrier(ax, T["WRITE"][1], "close")
save(fig, "fig5_loop_onelane")

# Figure 6: lane phases around a barrier entry (4.4)
fig, ax = frame("Figure 6. WRITE with a barrier entry between two lane phases (4.4)")
common(ax, write_main=False)
w0, w1 = T["WRITE"]
a, b = w0 + 1.1, w0 + 1.7
for i, r in enumerate(ROWS):
    block(ax, r, w0, a, C["lane"], f"lane {i}", fc="white")
    block(ax, r, b, w1, C["lane"], f"lane {i}", fc="white")
block(ax, "main", a, b, C["B"], "B", fc="white")
barrier(ax, w0, "open")
barrier(ax, a, "close")
barrier(ax, b, "open")
barrier(ax, w1, "close")
save(fig, "fig6_loop_barrier")

# Figure 7: STREAM (4.5)
fig, ax = frame("Figure 7. WRITE with a STREAM phase (4.5)")
common(ax, write_main=False)
block(ax, "main", *T["WRITE"], C["WRITE"], "WRITE: main executes in order S")
for r in ROWS[1:]:
    block(ax, r, *T["WRITE"], C["STREAM"], "STREAM: send finished replies")
barrier(ax, T["WRITE"][0], "open")
barrier(ax, T["WRITE"][1], "close")
save(fig, "fig7_loop_stream")
print("ok")

# Figure 9: what the barrier makes visible, one lane phase between two barrier lines (5.2)
fig, ax = plt.subplots(figsize=(10, 4.2), dpi=200)
ax.set_xlim(-0.05, 8.5)
ax.set_ylim(-1.75, 4.0)
ax.set_yticks([Y[r] for r in ROWS])
ax.set_yticklabels(["main", "IO 1 (lane 1)", "IO 2 (lane 2)", "IO 3 (lane 3)"], fontsize=10)
ax.set_xticks([])
for sp in ("top", "right", "bottom", "left"):
    ax.spines[sp].set_visible(False)
ax.tick_params(axis="y", length=0)
for r in ROWS:
    ax.plot([0, 8.4], [Y[r], Y[r]], color="#AAAAAA", linewidth=1.0, zorder=0)
ax.set_title("Figure 9. What the phase barrier makes visible, around one lane phase (5.2)", fontsize=10.5, loc="left")
ax.text(-0.05, 3.62, "barrier:", ha="left", va="bottom", fontsize=9)
x_open, x_close = 2.6, 5.6
block(ax, "main", 0.2, x_open, C["WRITE"], "main writes before the phase\n(for example a barrier entry)", fs=9)
for i, r in enumerate(ROWS):
    block(ax, r, x_open, x_close, C["lane"], f"lane {i}: writes only its own partitions", fc="white", fs=9)
block(ax, "main", x_close, 8.4, C["WRITE"], "main reads every lane's result\n(replay in T order)", fs=9)
# dashed barrier lines end at the bottom of the IO 3 row (y = -0.4)
y_bot = Y["IO 3"] - 0.4
for x, kind in ((x_open, "open (release / acquire)"), (x_close, "close (release / acquire)")):
    ax.plot([x, x], [y_bot, 3.55], color="black", linewidth=0.9, linestyle=(0, (3, 2)))
    ax.text(x, 3.62, kind, ha="center", va="bottom", fontsize=9)
# straight vertical arrows: orange just right of the open line, main down to each lane;
# blue just left of the close line, each lane up to main
for r in ROWS[1:]:
    ax.annotate("", xy=(x_open + 0.22, Y[r] + 0.38), xytext=(x_open + 0.22, Y["main"] - 0.38),
                arrowprops=dict(arrowstyle="->", lw=1.1, color="#D55E00", shrinkA=0, shrinkB=0))
    ax.annotate("", xy=(x_close - 0.22, Y["main"] - 0.38), xytext=(x_close - 0.22, Y[r] + 0.38),
                arrowprops=dict(arrowstyle="->", lw=1.1, color="#0072B2", shrinkA=0, shrinkB=0))
ax.text(x_open, -0.95, "orange arrows: main's writes before the open are visible to every lane", fontsize=9, color="#D55E00", ha="left")
ax.text(x_open, -1.25, "blue arrows: every lane's writes are visible to main after the close", fontsize=9, color="#0072B2", ha="left")
ax.text(x_open, -1.55, "inside the phase no thread reads another lane's partition", fontsize=9, ha="left")
save(fig, "fig9_barrier_visibility")
print("ok fig9")
