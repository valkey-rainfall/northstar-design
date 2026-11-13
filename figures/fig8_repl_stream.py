# Figure for section 4.9.4 of the North Star design doc: the replication
# stream a SET load produces, against the one-TCP-flow cap of the hosts.
# Stream bytes per SET are computed from RESP (16-byte key and value: 59 B);
# the two measured points are from the cross-host replication runs of 4.9.2
# (results/replication/summary.md); the cap is results/one-flow-cap.md.
# Palette: Okabe-Ito (color-blind safe), as fig_timelines.py. Text 9 pt or larger.
import os
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

BYTES_PER_SET = 59          # *3, $3 SET, $16 key, $16 value, CR LF each line
CAP_GBPS = 9.5              # one TCP flow between these instance types
PEAK_MSETS = 43.38          # Figure 2, C at 62 IO threads, no replica attached


def gbps(m_sets):
    return m_sets * 1e6 * BYTES_PER_SET * 8 / 1e9


cap_msets = CAP_GBPS * 1e9 / 8 / BYTES_PER_SET / 1e6

fig, ax = plt.subplots(figsize=(8, 4.6), dpi=200)
xs = [0, 46]
ax.plot(xs, [gbps(x) for x in xs], color="#0072B2", linewidth=1.6,
        label="stream at 59 bytes per SET (computed)")
ax.axhline(CAP_GBPS, color="#D55E00", linewidth=1.4, linestyle=(0, (5, 3)),
           label="one TCP flow, about 9.5 Gbit/s (measured, earlier host pair)")
ax.fill_between([cap_msets, 46], 0, 24, color="#D55E00", alpha=0.08, linewidth=0)
ax.text(cap_msets + 0.6, 1.0, "more than one\nlink can carry", fontsize=9, color="#D55E00",
        va="bottom")

# measured cross-host stream rates (stream MB/s from the replication runs)
ax.plot([1.398], [82.4e6 * 8 / 1e9], "o", color="#999999", markersize=7,
        label="measured, stock with a replica (1.40 M SET/s)")
ax.plot([2.746], [161.9e6 * 8 / 1e9], "s", color="#009E73", markersize=7,
        label="measured, S1 with a replica (2.75 M SET/s)")
# computed peak of Figure 2
ax.plot([PEAK_MSETS], [gbps(PEAK_MSETS)], "D", markerfacecolor="white",
        markeredgecolor="#0072B2", markeredgewidth=1.6, markersize=8,
        label="computed, Figure 2 peak without a replica (43.4 M SET/s)")
ax.annotate(f"{gbps(PEAK_MSETS):.1f} Gbit/s", xy=(PEAK_MSETS, gbps(PEAK_MSETS)),
            xytext=(PEAK_MSETS - 9.5, gbps(PEAK_MSETS) + 0.6), fontsize=9,
            arrowprops=dict(arrowstyle="->", lw=0.8))
ax.annotate(f"cap reached at {cap_msets:.1f} M SET/s", xy=(cap_msets, CAP_GBPS),
            xytext=(cap_msets - 16.5, CAP_GBPS + 3.2), fontsize=9,
            arrowprops=dict(arrowstyle="->", lw=0.8))

ax.set_xlim(0, 46)
ax.set_ylim(0, 24)
ax.set_xlabel("SET commands a second on the primary (millions), 16-byte keys and values", fontsize=10)
ax.set_ylabel("replication stream (Gbit/s)", fontsize=10)
ax.tick_params(labelsize=9)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.legend(loc="upper left", fontsize=9, frameon=False)
ax.set_title("Figure 8. The replication stream of a SET load against one TCP flow (4.9.4)",
             fontsize=10.5, loc="left")
for ext in ("png", "svg"):
    fig.savefig(os.path.join(HERE, f"fig8_repl_stream.{ext}"), bbox_inches="tight")
