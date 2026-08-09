"""
D0(무예약) <-> D1(1채널예약) 균형 전환점을 P75~P90 구간에서 0.5 단위로 정밀 탐색.

기존에 계산했던 셀당 200개 누출율 표본(seed=0..199, compute_payoff_matrices_by_percentile와
동일한 시드 규칙)을 그대로 재사용해서 percentile 값만 촘촘히 이동시킨다 - 시뮬레이션 재실행 없이
np.percentile 보간만으로 스캔 가능.
"""

import csv

import nashpy as nash
import numpy as np

from game_theory import (DEFENDER_STRATEGIES, compute_payoff_matrices_by_percentile,
                          equilibria_to_rows)

N_REPLICATIONS = 200
SCAN_START, SCAN_END, SCAN_STEP = 75.0, 90.0, 0.5

if __name__ == "__main__":
    percentiles = list(np.arange(SCAN_START, SCAN_END + 1e-9, SCAN_STEP))
    defender_names, attacker_names, matrices, samples = compute_payoff_matrices_by_percentile(
        percentiles, n_replications=N_REPLICATIONS)

    scan_rows = []
    prev_defender = None
    crossover_points = []

    print(f"{'percentile':>10}  {'defender':<16}{'attacker':<16}{'D0 vs A2':>10}{'D1 vs A2':>10}{'D2 vs A2':>10}")
    for p in percentiles:
        A, B = matrices[p]
        game = nash.Game(A, B)
        equilibria = list(game.support_enumeration())
        rows = equilibria_to_rows(defender_names, attacker_names, game, equilibria, p)
        # 이 게임의 균형은 항상 유일한 순수전략으로 관찰됨 (첫 번째 균형 사용)
        eq = rows[0]

        d0_idx = defender_names.index("D0_무예약")
        d1_idx = defender_names.index("D1_1채널예약")
        d2_idx = defender_names.index("D2_2채널예약")
        a2_idx = attacker_names.index("A2_무인기포화")

        scan_rows.append({
            "percentile": p,
            "defender_equilibrium": eq["defender_strategy"],
            "attacker_equilibrium": eq["attacker_strategy"],
            "leak_rate_D0_vs_A2": B[d0_idx, a2_idx],
            "leak_rate_D1_vs_A2": B[d1_idx, a2_idx],
            "leak_rate_D2_vs_A2": B[d2_idx, a2_idx],
        })

        print(f"P{p:>9.1f}  {eq['defender_strategy']:<16}{eq['attacker_strategy']:<16}"
              f"{B[d0_idx, a2_idx]*100:>9.1f}%{B[d1_idx, a2_idx]*100:>9.1f}%{B[d2_idx, a2_idx]*100:>9.1f}%")

        if prev_defender is not None and eq["defender_strategy"] != prev_defender:
            crossover_points.append((p, prev_defender, eq["defender_strategy"]))
        prev_defender = eq["defender_strategy"]

    print(f"\n{'=' * 60}\n전환점\n{'=' * 60}")
    if crossover_points:
        for p, before, after in crossover_points:
            print(f"P{p - SCAN_STEP:.1f} -> P{p:.1f} 구간에서 균형이 {before} -> {after} 로 전환")
    else:
        print("스캔 구간 내에서 전환이 관찰되지 않았습니다.")

    # D0 vs A2 와 D1 vs A2 누출율 곡선이 실제로 교차하는 지점도 보간으로 추정
    leak_d0 = np.array([r["leak_rate_D0_vs_A2"] for r in scan_rows])
    leak_d1 = np.array([r["leak_rate_D1_vs_A2"] for r in scan_rows])
    diff = leak_d0 - leak_d1  # D0가 더 나쁘면(양수) D1이 우세
    sign_changes = np.where(np.diff(np.sign(diff)) != 0)[0]
    if len(sign_changes) > 0:
        i = sign_changes[0]
        p_a, p_b = percentiles[i], percentiles[i + 1]
        d_a, d_b = diff[i], diff[i + 1]
        # 선형 보간으로 diff==0 인 percentile 추정
        p_cross = p_a + (0 - d_a) * (p_b - p_a) / (d_b - d_a)
        print(f"\nD0 vs A2 / D1 vs A2 누출율 곡선의 선형보간 교차점: 약 P{p_cross:.2f}")

    with open("game_theory_crossover_scan.csv", "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["percentile", "defender_equilibrium", "attacker_equilibrium",
                      "leak_rate_D0_vs_A2", "leak_rate_D1_vs_A2", "leak_rate_D2_vs_A2"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scan_rows)
    print("\nCSV 저장: game_theory_crossover_scan.csv")
