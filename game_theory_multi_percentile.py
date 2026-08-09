"""
P50 / P75 / P90 / P95 여러 리스크 수준에서 내시균형이 어떻게 바뀌는지 확인하고,
지금까지 상세 리포트를 돌리지 않은 새로운 균형(defender, attacker) 조합이 있으면
equilibrium_report.py와 동일한 방식(집계 기준값 + 단일 실행 disclaimer)으로 리포트를 만든다.
"""

import csv

import nashpy as nash
import numpy as np

from air_defense_sim import SIM_TIME, print_report, save_report_csv
from game_theory import (ATTACKER_STRATEGIES, DEFENDER_STRATEGIES,
                          compute_cell_reference, compute_payoff_matrices_by_percentile,
                          equilibria_to_rows, print_equilibria, print_payoff_table,
                          run_reserved_simulation)

PERCENTILES = [50, 75, 90, 95]
N_REPLICATIONS = 200
SEED = 0

# 이미 상세 리포트를 돌린 조합 (equilibrium_report.py 결과) -> 중복 실행 방지
ALREADY_REPORTED = {
    ("D0_무예약", "A2_무인기포화"),
    ("D1_1채널예약", "A2_무인기포화"),
}


def run_detail_report(dname, aname, ref):
    k = DEFENDER_STRATEGIES[dname]
    mix = ATTACKER_STRATEGIES[aname]
    stats = run_reserved_simulation(k, mix, seed=SEED)
    rows = stats.summary()
    single_gen = sum(r["generated"] for r in rows)
    single_leak = sum(r["leaked"] for r in rows)
    single_leak_rate = single_leak / single_gen if single_gen else 0.0

    print(f"\n{'=' * 70}")
    print(f"신규 균형 상세 리포트: {dname} vs {aname}")
    print(f"{'=' * 70}")
    print(f"[집계 기준값, N={N_REPLICATIONS}회 반복] "
          f"평균 누출율={ref['mean_leak_rate']*100:.1f}%  "
          f"P95={ref['p95_leak_rate']*100:.1f}%  "
          f"(범위 {ref['min_leak_rate']*100:.1f}%~{ref['max_leak_rate']*100:.1f}%, "
          f"표준편차 {ref['std_leak_rate']*100:.1f}%p)")
    print(f"[아래는 그중 단 1회(seed={SEED})의 실행 결과입니다 — '균형 페이오프' 자체가 "
          f"아니라 확률적 변동성을 보여주는 예시입니다]")
    print(f"  -> 이번 단일 실행 누출율 = {single_leak_rate*100:.1f}% "
          f"(집계 평균과 {abs(single_leak_rate-ref['mean_leak_rate'])*100:.1f}%p 차이)")

    print_report(stats, f"{dname} / {aname}")

    csv_path = f"equilibrium_report_{dname}_vs_{aname}.csv"
    save_report_csv(stats, f"{dname}/{aname}", SIM_TIME, SEED, path=csv_path)
    with open(csv_path, "a", encoding="utf-8-sig") as f:
        f.write("\n# NOTE: 위 표는 단일 실행(seed=%d) 결과입니다. "
                "아래는 같은 전략 조합을 N=%d회 반복한 집계 기준값(참고용)입니다.\n"
                % (SEED, N_REPLICATIONS))
        f.write("# metric,value\n")
        f.write(f"# mean_leak_rate,{ref['mean_leak_rate']}\n")
        f.write(f"# p95_leak_rate,{ref['p95_leak_rate']}\n")
        f.write(f"# min_leak_rate,{ref['min_leak_rate']}\n")
        f.write(f"# max_leak_rate,{ref['max_leak_rate']}\n")
        f.write(f"# std_leak_rate,{ref['std_leak_rate']}\n")
        f.write(f"# single_run_leak_rate,{single_leak_rate}\n")
    print(f"CSV 저장(집계 기준값 주석 포함): {csv_path}")


if __name__ == "__main__":
    defender_names, attacker_names, matrices, samples = compute_payoff_matrices_by_percentile(
        PERCENTILES, n_replications=N_REPLICATIONS)

    all_rows = []
    pure_pairs_found = set()

    for p in PERCENTILES:
        A, B = matrices[p]
        print_payoff_table(defender_names, attacker_names, B, title=f"페이오프 행렬 - P{p} 누출율 (%)")
        game = nash.Game(A, B)
        equilibria = list(game.support_enumeration())
        print_equilibria(defender_names, attacker_names, game, equilibria, title=f"내시균형 - P{p} 기준")

        rows = equilibria_to_rows(defender_names, attacker_names, game, equilibria, p)
        all_rows.extend(rows)
        for r in rows:
            if r["defender_strategy"] != "mixed" and r["attacker_strategy"] != "mixed":
                pure_pairs_found.add((r["defender_strategy"], r["attacker_strategy"]))

    # 요약 테이블
    print(f"\n{'=' * 70}\n리스크 수준별 균형 요약\n{'=' * 70}")
    print(f"{'percentile':>10}  {'defender':<16}{'attacker':<16}{'kill_rate':>10}{'leak_rate':>10}")
    for r in all_rows:
        print(f"P{r['percentile']:>9}  {r['defender_strategy']:<16}{r['attacker_strategy']:<16}"
              f"{r['defender_payoff_killrate']*100:>9.1f}%{r['attacker_payoff_leakrate']*100:>9.1f}%")

    fieldnames = (["percentile", "equilibrium_id", "defender_strategy", "attacker_strategy",
                   "defender_payoff_killrate", "attacker_payoff_leakrate"]
                  + [f"defender_p_{d}" for d in defender_names]
                  + [f"attacker_p_{a}" for a in attacker_names])
    with open("game_theory_equilibria_by_percentile.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print("\nCSV 저장: game_theory_equilibria_by_percentile.csv")

    # 아직 상세 리포트를 안 돌린 신규 순수전략 균형에 대해서만 리포트 실행
    new_pairs = pure_pairs_found - ALREADY_REPORTED
    if new_pairs:
        print(f"\n신규 균형 {len(new_pairs)}개 발견 -> 상세 리포트 실행: {sorted(new_pairs)}")
        for dname, aname in sorted(new_pairs):
            ref = compute_cell_reference(dname, aname, n_replications=N_REPLICATIONS, percentile=95)
            run_detail_report(dname, aname, ref)
    else:
        print("\n이미 리포트를 돌린 조합 외의 신규 순수전략 균형은 없습니다.")
