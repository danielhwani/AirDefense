"""
채널 수(NUM_CHANNELS) sweep: 1, 2, 3, 5개에 대해 각각 여러 번(다른 시드) 반복 실행하고
요격 성공률(격추율) / 누출율 / 평균 대기시간을 비교 시각화한다.
"""

import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from air_defense_sim import THREATS, run_simulation, SIM_TIME

# ----------------------------
# 한글 폰트 설정
# ----------------------------
plt.rcParams["font.family"] = "Noto Sans CJK KR"
plt.rcParams["axes.unicode_minus"] = False

# ----------------------------
# 팔레트 (dataviz 스킬 reference/palette.md 의 검증된 기본 팔레트)
# ----------------------------
COLOR_SURFACE = "#fcfcfb"
COLOR_PRIMARY_INK = "#0b0b0b"
COLOR_SECONDARY_INK = "#52514e"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"
COLOR_AXIS = "#c3c2b7"
COLOR_BLUE = "#2a78d6"    # 격추(성공)
COLOR_RED = "#e34948"     # 누출(실패)

NUM_CHANNELS_LIST = [1, 2, 3, 5]
N_REPLICATIONS = 30  # 채널 수마다 서로 다른 시드로 반복해 결과를 평균


def sweep():
    """채널 수마다 N_REPLICATIONS회(시드 0..N-1) 반복 실행. 요약 결과와
    반복별 원본(raw) 결과를 함께 반환해 재현/검증이 가능하게 한다."""
    results = []
    raw_rows = []
    for n in NUM_CHANNELS_LIST:
        kill_rates, leak_rates, avg_waits = [], [], []
        for rep in range(N_REPLICATIONS):
            stats = run_simulation(num_channels=n, sim_time=SIM_TIME, seed=rep)
            rows = stats.summary()
            total_gen = sum(r["generated"] for r in rows)
            total_kill = sum(r["killed"] for r in rows)
            total_leak = sum(r["leaked"] for r in rows)
            all_waits = [w for name in THREATS for w in stats.wait_times[name]]

            kill_rate = total_kill / total_gen if total_gen else 0.0
            leak_rate = total_leak / total_gen if total_gen else 0.0
            avg_wait = sum(all_waits) / len(all_waits) if all_waits else 0.0

            kill_rates.append(kill_rate)
            leak_rates.append(leak_rate)
            avg_waits.append(avg_wait)
            raw_rows.append({
                "num_channels": n,
                "seed": rep,
                "sim_time": SIM_TIME,
                "kill_rate": kill_rate,
                "leak_rate": leak_rate,
                "avg_wait": avg_wait,
            })

        results.append({
            "num_channels": n,
            "kill_rate": sum(kill_rates) / N_REPLICATIONS,
            "leak_rate": sum(leak_rates) / N_REPLICATIONS,
            "avg_wait": sum(avg_waits) / N_REPLICATIONS,
        })
    return results, raw_rows


def print_table(results):
    print(f"\n=== 채널 수 Sweep 결과 (각 {N_REPLICATIONS}회 반복 평균, sim_time={SIM_TIME}분) ===")
    header = f"{'채널수':>6}{'격추율':>10}{'누출율':>10}{'평균대기(분)':>14}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['num_channels']:>6}{r['kill_rate']*100:>9.1f}%{r['leak_rate']*100:>9.1f}%{r['avg_wait']:>14.2f}")


def _style_axes(ax):
    ax.set_facecolor(COLOR_SURFACE)
    ax.grid(True, color=COLOR_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLOR_AXIS)
    ax.tick_params(colors=COLOR_MUTED)
    ax.xaxis.label.set_color(COLOR_SECONDARY_INK)
    ax.yaxis.label.set_color(COLOR_SECONDARY_INK)


def plot(results, out_path="channel_sweep.png"):
    channels = [r["num_channels"] for r in results]
    kill = [r["kill_rate"] * 100 for r in results]
    leak = [r["leak_rate"] * 100 for r in results]
    wait = [r["avg_wait"] for r in results]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), facecolor=COLOR_SURFACE)

    # ---- 왼쪽: 격추율 / 누출율 ----
    ax = axes[0]
    _style_axes(ax)
    ax.plot(channels, kill, color=COLOR_BLUE, linewidth=2, marker="o", markersize=6, label="격추율")
    ax.plot(channels, leak, color=COLOR_RED, linewidth=2, marker="o", markersize=6, label="누출율")
    ax.set_xticks(channels)
    ax.set_xlabel("교전 채널 수")
    ax.set_ylabel("비율 (%)")
    ax.set_title("채널 수별 요격 성공률 / 누출률", color=COLOR_PRIMARY_INK, fontsize=12,
                  fontweight="bold", loc="left")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, labelcolor=COLOR_SECONDARY_INK)
    ax.annotate(f"{kill[-1]:.1f}%", (channels[-1], kill[-1]), textcoords="offset points",
                xytext=(8, 4), color=COLOR_BLUE, fontsize=9, fontweight="bold")
    ax.annotate(f"{leak[-1]:.1f}%", (channels[-1], leak[-1]), textcoords="offset points",
                xytext=(8, -12), color=COLOR_RED, fontsize=9, fontweight="bold")

    # ---- 오른쪽: 평균 대기시간 ----
    ax2 = axes[1]
    _style_axes(ax2)
    ax2.plot(channels, wait, color=COLOR_BLUE, linewidth=2, marker="o", markersize=6)
    ax2.set_xticks(channels)
    ax2.set_xlabel("교전 채널 수")
    ax2.set_ylabel("평균 대기시간 (분)")
    ax2.set_title("채널 수별 평균 대기시간", color=COLOR_PRIMARY_INK, fontsize=12,
                   fontweight="bold", loc="left")
    ax2.set_ylim(0, max(wait) * 1.3 if max(wait) > 0 else 1)
    for x, y in zip(channels, wait):
        ax2.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 8),
                     color=COLOR_SECONDARY_INK, fontsize=8, ha="center")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=COLOR_SURFACE)
    print(f"그래프 저장: {out_path}")


def save_summary_csv(results, path="channel_sweep_summary.csv"):
    fieldnames = ["num_channels", "n_replications", "sim_time", "kill_rate", "leak_rate", "avg_wait"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = dict(r)
            row["n_replications"] = N_REPLICATIONS
            row["sim_time"] = SIM_TIME
            writer.writerow(row)
    print(f"CSV 저장: {path}")


def save_raw_csv(raw_rows, path="channel_sweep_raw.csv"):
    fieldnames = ["num_channels", "seed", "sim_time", "kill_rate", "leak_rate", "avg_wait"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(raw_rows)
    print(f"CSV 저장: {path} (반복별 원본 데이터, seed=0..{N_REPLICATIONS - 1})")


if __name__ == "__main__":
    results, raw_rows = sweep()
    print_table(results)
    plot(results)
    save_summary_csv(results)
    save_raw_csv(raw_rows)
