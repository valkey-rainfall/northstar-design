# Figure 2 for the North Star design doc: SET throughput vs io-threads.
# Data: results/p22.md, "Step 2: SET sweep (P22SET)", 2026-11-09/10 (design doc section 6.3).
# The two EC2 hosts of section 6.1, Linux 6.18, SET 16 B keys and values, 3 M keys preloaded and
# overwritten, pipeline 64, 2,400 connections, client cachecannon 82a79d0 (2 processes x 88 threads),
# mean of 2 tasks x 5 reps per point; io-threads 48 and 62 are the mean of 3 tasks.
# Builds: C = ceaa1101d (io-threads-epoll-thread yes from io-threads 4, the first sweep point >= 3;
# default config at io-threads 1 and 2, where the epoll thread is not available), stock = 2a23bcda0.
# Same style as fig1_scaling.py; C and stock only.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

io = [1, 2, 4, 8, 16, 32, 48, 62]
c = [1.625, 1.939, 2.874, 6.817, 14.127, 26.183, 36.802, 43.378]
stock = [1.778, 2.589, 2.607, 2.570, 2.540, 2.507, 2.491, 2.465]

fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
ax.plot(io, c, "o-", color="#1f77b4", lw=2.2, label="North Star proof of concept at C")
ax.plot(io, stock, "o-", color="#d62728", lw=2.2, label="stock server")

ax.annotate("43 M ops/s\n(18x stock)", xy=(62, 43.378), xytext=(40, 41),
            arrowprops=dict(arrowstyle="->", lw=1), fontsize=9)
ax.annotate("stock: about 2.5 M ops/s\nfrom io-threads 2 up", xy=(32, 2.507), xytext=(36, 10),
            arrowprops=dict(arrowstyle="->", lw=1), fontsize=9)
ax.set_xlabel("io-threads (server IO threads)")
ax.set_ylabel("SET throughput (million commands per second)")
ax.set_title("SET throughput vs IO threads, 16-byte values, real network")
ax.set_xlim(0, 66)
ax.set_ylim(0, 48)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=8, frameon=False)
fig.text(0.01, 0.01, "At io-threads 1 and 2, C runs its default config (the collector thread needs io-threads 3 or more).",
         fontsize=7, color="#555555")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(__file__.replace("fig2_set_scaling.py", "fig2_set_scaling.png"))
