"""
내시균형 지점(들)에서 상세(표적별) 리포트를 한 번 실행해본다.
균형 계산 자체에는 불필요하지만, 균형이 실제로 어떤 시나리오인지 감을 잡기 위한 예시 실행.

주의: 아래 표적별 상세 리포트는 seed=1개짜리 '단일 실행' 결과다. 균형 계산에 쓰인
페이오프(평균 또는 P95)는 N회 반복의 집계치이므로 단일 실행 값과 다를 수 있다 — 이는 버그가
아니라 시뮬레이션의 확률적 변동성 때문이며, 각 리포트 상단에 집계 기준값을 함께 표시해
혼동을 막는다.
"""

from air_defense_sim import SIM_TIME, print_report, save_report_csv
from game_theory import (ATTACKER_STRATEGIES, DEFENDER_STRATEGIES,
                          compute_cell_reference, run_reserved_simulation)

SEED = 0
REFERENCE_N_REPLICATIONS = 200
REFERENCE_PERCENTILE = 95

EQUILIBRIA_TO_RUN = [
    ("평균 기준 균형", "D0_무예약", "A2_무인기포화"),
    ("P95 리스크 기준 균형", "D1_1채널예약", "A2_무인기포화"),
]

if __name__ == "__main__":
    for label, dname, aname in EQUILIBRIA_TO_RUN:
        k = DEFENDER_STRATEGIES[dname]
        mix = ATTACKER_STRATEGIES[aname]

        ref = compute_cell_reference(dname, aname, n_replications=REFERENCE_N_REPLICATIONS,
                                      percentile=REFERENCE_PERCENTILE)
        stats = run_reserved_simulation(k, mix, seed=SEED)
        rows = stats.summary()
        single_gen = sum(r["generated"] for r in rows)
        single_leak = sum(r["leaked"] for r in rows)
        single_leak_rate = single_leak / single_gen if single_gen else 0.0

        print(f"\n{'=' * 70}")
        print(f"{label}: {dname} vs {aname}")
        print(f"{'=' * 70}")
        print(f"[집계 기준값, N={REFERENCE_N_REPLICATIONS}회 반복] "
              f"평균 누출율={ref['mean_leak_rate']*100:.1f}%  "
              f"P{REFERENCE_PERCENTILE}={ref[f'p{REFERENCE_PERCENTILE}_leak_rate']*100:.1f}%  "
              f"(범위 {ref['min_leak_rate']*100:.1f}%~{ref['max_leak_rate']*100:.1f}%, "
              f"표준편차 {ref['std_leak_rate']*100:.1f}%p)")
        print(f"[아래는 그중 단 1회(seed={SEED})의 실행 결과입니다 — 이 값 자체는 "
              f"'균형 페이오프'가 아니라 확률적 변동성을 보여주는 예시입니다]")
        print(f"  -> 이번 단일 실행 누출율 = {single_leak_rate*100:.1f}% "
              f"(집계 평균과 {abs(single_leak_rate-ref['mean_leak_rate'])*100:.1f}%p 차이)")

        print_report(stats, f"{dname} / {aname}")

        csv_path = f"equilibrium_report_{dname}_vs_{aname}.csv"
        save_report_csv(stats, f"{dname}/{aname}", SIM_TIME, SEED, path=csv_path)

        # CSV에 '이 값은 단일 실행 표본' 임을 알려주는 기준값 메타 행 추가
        with open(csv_path, "a", encoding="utf-8-sig") as f:
            f.write("\n")
            f.write("# NOTE: 위 표는 단일 실행(seed=%d) 결과입니다. "
                    "아래는 같은 전략 조합을 N=%d회 반복한 집계 기준값(참고용)입니다.\n"
                    % (SEED, REFERENCE_N_REPLICATIONS))
            f.write("# metric,value\n")
            f.write(f"# mean_leak_rate,{ref['mean_leak_rate']}\n")
            f.write(f"# p{REFERENCE_PERCENTILE}_leak_rate,{ref[f'p{REFERENCE_PERCENTILE}_leak_rate']}\n")
            f.write(f"# min_leak_rate,{ref['min_leak_rate']}\n")
            f.write(f"# max_leak_rate,{ref['max_leak_rate']}\n")
            f.write(f"# std_leak_rate,{ref['std_leak_rate']}\n")
            f.write(f"# single_run_leak_rate,{single_leak_rate}\n")
        print(f"CSV에 집계 기준값 주석 추가 완료: {csv_path}")
