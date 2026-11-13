# Figure 1 for the North Star design doc: GET throughput vs io-threads.
# Data: results/p21.md, "Figure 1 sweep (P21F1)", 2026-11-07/08 (design doc section 6.4).
# The two EC2 hosts of section 6.1, Linux 6.18, GET 16 B, pipeline 64,
# 2,400 connections, client cachecannon 82a79d0 (2 processes x 88 threads),
# mean of 2 tasks x 5 reps per point; C at io-threads 48 and 62 is the mean of
# 3 tasks (rounds R1-R3, R3 run 2026-11-08 on the same boot).
# Builds: C = ceaa1101d (io-threads-epoll-thread yes from io-threads 4; default
# config at io-threads 1 and 2, where the epoll thread is not available),
# stock = 2a23bcda0. The figure shows C and stock only.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

io = [1, 2, 4, 8, 16, 32, 48, 62]
c = [2.27, 7.38, 11.30, 26.40, 55.78, 113.08, 164.99, 199.96]
stock = [2.42, 3.98, 3.99, 3.84, 3.83, 3.78, 3.67, 3.59]

fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
ax.plot(io, c, "o-", color="#1f77b4", lw=2.2, label="North Star proof of concept at C")
ax.plot(io, stock, "o-", color="#d62728", lw=2.2, label="stock server")

ax.annotate("200 M ops/s\n(56x stock)", xy=(62, 199.96), xytext=(38, 187),
            arrowprops=dict(arrowstyle="->", lw=1), fontsize=9)
ax.annotate("stock: about 4 M ops/s\nfrom io-threads 2 up", xy=(32, 3.78), xytext=(36, 30),
            arrowprops=dict(arrowstyle="->", lw=1), fontsize=9)
ax.set_xlabel("io-threads (server IO threads)")
ax.set_ylabel("GET throughput (million commands per second)")
ax.set_title("GET throughput vs IO threads, 16-byte values, real network")
ax.set_xlim(0, 66)
ax.set_ylim(0, 220)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=8, frameon=False)
fig.tight_layout()
fig.savefig(__file__.replace("fig1_scaling.py", "fig1_scaling.png"))
