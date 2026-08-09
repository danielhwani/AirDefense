"""
대공방어 자원배분 게임이론 레이어

- 방어자 전략: 고우선순위(탄도미사일/순항미사일) 전용 예약 채널 수 K (0/1/2, 총 3채널 중)
- 공격자 전략: 총 공격 예산(발생률)은 고정, 4개 위협 유형에 대한 구성비만 변경
- 페이오프: 방어자=격추율, 공격자=누출율 (constant-sum, kill_rate + leak_rate = 1)
- 각 (방어자, 공격자) 전략 조합의 페이오프는 SimPy 시뮬레이션을 N회 반복해 평균 낸 값
- nashpy로 내시균형(순수/혼합) 계산

채널 예약 구현: 고우선순위 표적은 예약 채널 풀(reserved_pool)과 공용 채널 풀(shared_pool)에
동시에 요청을 걸고 먼저 허가되는 쪽을 사용한다. 두 풀이 같은 시점에 동시에 허가되는 경우
(둘 다 여유가 있던 경우) 하나는 즉시 반납(release)하고, 아직 허가되지 않은 나머지 요청은
취소(cancel)해서 자원이 새지 않도록 한다. 저우선순위 표적은 공용 채널만 사용한다.
"""

import csv
import random

import nashpy as nash
import numpy as np
import simpy

from air_defense_sim import SIM_TIME, THREATS, Stats, _reload_and_release

NUM_CHANNELS = 3
HIGH_PRIORITY = {"탄도미사일", "순항미사일"}
N_REPLICATIONS = 30

# 공격자의 총 공격 예산(발생률 총합)은 베이스라인과 동일하게 고정
BASELINE_LAMBDA = sum(1.0 / p["mean_interarrival"] for p in THREATS.values())

DEFENDER_STRATEGIES = {
    "D0_무예약": 0,
    "D1_1채널예약": 1,
    "D2_2채널예약": 2,
}

ATTACKER_STRATEGIES = {
    "A1_균형": {"탄도미사일": 0.25, "순항미사일": 0.25, "항공기": 0.25, "무인기": 0.25},
    "A2_무인기포화": {"탄도미사일": 0.05, "순항미사일": 0.10, "항공기": 0.15, "무인기": 0.70},
    "A3_고가치집중": {"탄도미사일": 0.40, "순항미사일": 0.35, "항공기": 0.15, "무인기": 0.10},
}


def _make_threats_for_mix(mix):
    """공격자 위협 구성비(mix)를 반영해 mean_interarrival만 재계산한 THREATS 사본 생성"""
    threats = {}
    for name, params in THREATS.items():
        p = dict(params)
        rate = mix[name] * BASELINE_LAMBDA
        p["mean_interarrival"] = 1.0 / rate
        threats[name] = p
    return threats


def _fire_shot_reserved(env, params, reserved_pool, shared_pool, is_high_priority):
    """
    사격 1회: 고우선순위 표적은 예약/공용 채널에 동시 요청 후 먼저 허가되는 쪽을 사용.
    둘 다 허가되면 하나는 반납, 미허가 쪽은 취소해 자원 누수를 막는다.
    """
    request_time = env.now

    if is_high_priority and reserved_pool is not None:
        req_r = reserved_pool.request(priority=params["priority"])
        req_s = shared_pool.request(priority=params["priority"])
        yield req_r | req_s

        if req_r.triggered and req_s.triggered:
            shared_pool.release(req_s)
            pool, req = reserved_pool, req_r
        elif req_r.triggered:
            req_s.cancel()
            pool, req = reserved_pool, req_r
        else:
            req_r.cancel()
            pool, req = shared_pool, req_s
    else:
        req = shared_pool.request(priority=params["priority"])
        yield req
        pool = shared_pool

    wait = env.now - request_time
    yield env.timeout(params["engagement_time"])
    hit = random.random() < params["pk"]

    env.process(_reload_and_release(env, pool, req, params["reload_time"]))
    return hit, wait


def _threat_process_reserved(env, name, params, reserved_pool, shared_pool, stats):
    stats.generated[name] += 1
    is_high = name in HIGH_PRIORITY
    killed = False

    for shot_num in range(1, params["max_shots"] + 1):
        hit, wait = yield env.process(
            _fire_shot_reserved(env, params, reserved_pool, shared_pool, is_high)
        )
        stats.shots_fired[name] += 1
        if shot_num == 1:
            stats.wait_times[name].append(wait)
            stats.engaged[name] += 1
        else:
            stats.reengagements[name] += 1

        if hit:
            stats.killed[name] += 1
            killed = True
            break

    if not killed:
        stats.missed[name] += 1


def _threat_generator_reserved(env, name, params, reserved_pool, shared_pool, stats):
    while True:
        yield env.timeout(random.expovariate(1.0 / params["mean_interarrival"]))
        env.process(_threat_process_reserved(env, name, params, reserved_pool, shared_pool, stats))


def run_reserved_simulation(reserved_k, mix, num_channels=NUM_CHANNELS, sim_time=SIM_TIME, seed=0):
    random.seed(seed)
    env = simpy.Environment()
    reserved_pool = simpy.PriorityResource(env, capacity=reserved_k) if reserved_k > 0 else None
    shared_pool = simpy.PriorityResource(env, capacity=num_channels - reserved_k)
    stats = Stats()

    for name, params in _make_threats_for_mix(mix).items():
        env.process(_threat_generator_reserved(env, name, params, reserved_pool, shared_pool, stats))

    env.run(until=sim_time)
    return stats


def leak_rate_distribution(reserved_k, mix, n_replications, seed_offset=0):
    """주어진 (방어자 K, 공격자 mix) 조합의 누출율 표본 리스트 (반복별 원값)"""
    leak_rates = []
    for rep in range(n_replications):
        stats = run_reserved_simulation(reserved_k, mix, seed=seed_offset + rep)
        rows = stats.summary()
        gen = sum(r["generated"] for r in rows)
        leak = sum(r["leaked"] for r in rows)
        leak_rates.append(leak / gen if gen else 0.0)
    return leak_rates


def compute_cell_reference(dname, aname, n_replications=200, percentile=95):
    """
    특정 (방어자, 공격자) 셀의 집계 기준값(평균/percentile)을 계산.
    단일 실행 리포트 등에서 '이 값은 N회 반복 집계치이고, 개별 실행은 이와 다를 수 있다'는
    기준선을 제공하기 위한 함수.
    """
    k = DEFENDER_STRATEGIES[dname]
    mix = ATTACKER_STRATEGIES[aname]
    leak_rates = np.array(leak_rate_distribution(k, mix, n_replications))
    return {
        "defender": dname,
        "attacker": aname,
        "n_replications": n_replications,
        "mean_leak_rate": float(leak_rates.mean()),
        "std_leak_rate": float(leak_rates.std()),
        "min_leak_rate": float(leak_rates.min()),
        "max_leak_rate": float(leak_rates.max()),
        f"p{percentile}_leak_rate": float(np.percentile(leak_rates, percentile)),
    }


def compute_payoff_matrix():
    """defender x attacker 페이오프 행렬(A=격추율, B=누출율)과 상세 결과를 계산"""
    defender_names = list(DEFENDER_STRATEGIES.keys())
    attacker_names = list(ATTACKER_STRATEGIES.keys())
    A = np.zeros((len(defender_names), len(attacker_names)))
    B = np.zeros((len(defender_names), len(attacker_names)))
    detail_rows = []

    for i, dname in enumerate(defender_names):
        k = DEFENDER_STRATEGIES[dname]
        for j, aname in enumerate(attacker_names):
            mix = ATTACKER_STRATEGIES[aname]
            leak_rates = []
            for rep in range(N_REPLICATIONS):
                stats = run_reserved_simulation(k, mix, seed=rep)
                rows = stats.summary()
                gen = sum(r["generated"] for r in rows)
                leak = sum(r["leaked"] for r in rows)
                leak_rates.append(leak / gen if gen else 0.0)

            avg_leak = sum(leak_rates) / N_REPLICATIONS
            A[i, j] = 1.0 - avg_leak
            B[i, j] = avg_leak
            detail_rows.append({
                "defender": dname, "attacker": aname,
                "kill_rate": 1.0 - avg_leak, "leak_rate": avg_leak,
            })

    return defender_names, attacker_names, A, B, detail_rows


def compute_payoff_matrix_risk(percentile=95, n_replications=200):
    """
    리스크 회피 페이오프: 각 (방어자, 공격자) 조합을 n_replications회 반복해
    누출율 분포의 percentile(기본 95) 분위값을 페이오프로 사용한다.

    leak_rate + kill_rate = 1 이 매 반복마다 성립하므로,
    P{percentile}(leak_rate) = 1 - P{100-percentile}(kill_rate) 관계가 그대로 유지된다.
    즉 방어자 payoff(1-P95_leak)는 "최악에 가까운 5% 시나리오에서의 격추율"이고,
    공격자 payoff(P95_leak)는 "공격자에게 가장 유리한 5% 시나리오의 누출율"이다.
    (mean 버전보다 표본이 훨씬 많이 필요해 반복 횟수를 30 -> 200으로 늘렸다.)
    """
    defender_names = list(DEFENDER_STRATEGIES.keys())
    attacker_names = list(ATTACKER_STRATEGIES.keys())
    A = np.zeros((len(defender_names), len(attacker_names)))
    B = np.zeros((len(defender_names), len(attacker_names)))
    detail_rows = []

    for i, dname in enumerate(defender_names):
        k = DEFENDER_STRATEGIES[dname]
        for j, aname in enumerate(attacker_names):
            mix = ATTACKER_STRATEGIES[aname]
            leak_rates = []
            for rep in range(n_replications):
                stats = run_reserved_simulation(k, mix, seed=rep)
                rows = stats.summary()
                gen = sum(r["generated"] for r in rows)
                leak = sum(r["leaked"] for r in rows)
                leak_rates.append(leak / gen if gen else 0.0)

            leak_arr = np.array(leak_rates)
            mean_leak = float(leak_arr.mean())
            p_leak = float(np.percentile(leak_arr, percentile))
            A[i, j] = 1.0 - p_leak
            B[i, j] = p_leak
            detail_rows.append({
                "defender": dname, "attacker": aname,
                "mean_leak_rate": mean_leak,
                "risk_leak_rate": p_leak,
                "defender_risk_payoff": 1.0 - p_leak,
                "attacker_risk_payoff": p_leak,
            })

    return defender_names, attacker_names, A, B, detail_rows


def compute_payoff_matrices_by_percentile(percentiles, n_replications=200, seed_offset=0):
    """
    percentiles(예: [50,75,90,95])별 페이오프 행렬을 계산하되, 셀당 시뮬레이션 표본은
    한 번(n_replications회)만 뽑아서 여러 percentile 계산에 재사용한다
    (percentile마다 다시 시뮬레이션을 돌리는 낭비를 피함).
    반환: defender_names, attacker_names, {percentile: (A, B)}, {(i,j): 표본배열}
    """
    defender_names = list(DEFENDER_STRATEGIES.keys())
    attacker_names = list(ATTACKER_STRATEGIES.keys())

    samples = {}
    for i, dname in enumerate(defender_names):
        k = DEFENDER_STRATEGIES[dname]
        for j, aname in enumerate(attacker_names):
            mix = ATTACKER_STRATEGIES[aname]
            samples[(i, j)] = np.array(leak_rate_distribution(k, mix, n_replications, seed_offset))

    matrices = {}
    for p in percentiles:
        A = np.zeros((len(defender_names), len(attacker_names)))
        B = np.zeros((len(defender_names), len(attacker_names)))
        for (i, j), arr in samples.items():
            val = float(np.percentile(arr, p))
            A[i, j] = 1.0 - val
            B[i, j] = val
        matrices[p] = (A, B)

    return defender_names, attacker_names, matrices, samples


def equilibria_to_rows(defender_names, attacker_names, game, equilibria, percentile):
    """균형 목록을 CSV/요약용 행 딕셔너리 리스트로 변환. 순수전략이면 이름도 함께 기록."""
    rows = []
    for idx, (sigma_d, sigma_a) in enumerate(equilibria, start=1):
        payoff_d, payoff_a = game[sigma_d, sigma_a]
        d_is_pure = bool(np.any(np.isclose(sigma_d, 1.0)))
        a_is_pure = bool(np.any(np.isclose(sigma_a, 1.0)))
        row = {
            "percentile": percentile,
            "equilibrium_id": idx,
            "defender_strategy": defender_names[int(np.argmax(sigma_d))] if d_is_pure else "mixed",
            "attacker_strategy": attacker_names[int(np.argmax(sigma_a))] if a_is_pure else "mixed",
            "defender_payoff_killrate": payoff_d,
            "attacker_payoff_leakrate": payoff_a,
        }
        row.update({f"defender_p_{d}": p for d, p in zip(defender_names, sigma_d)})
        row.update({f"attacker_p_{a}": p for a, p in zip(attacker_names, sigma_a)})
        rows.append(row)
    return rows


def save_payoff_csv_risk(detail_rows, percentile, n_replications, path="game_theory_payoff_risk.csv"):
    fieldnames = ["defender", "attacker", "mean_leak_rate", "risk_leak_rate",
                  "defender_risk_payoff", "attacker_risk_payoff",
                  "percentile", "n_replications", "sim_time"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in detail_rows:
            row = dict(r)
            row["percentile"] = percentile
            row["n_replications"] = n_replications
            row["sim_time"] = SIM_TIME
            writer.writerow(row)
    print(f"\nCSV 저장: {path}")


def print_payoff_table(defender_names, attacker_names, B, title="페이오프 행렬 (공격자 누출율, %)"):
    print(f"\n=== {title} ===")
    header = f"{'':<16}" + "".join(f"{a:>16}" for a in attacker_names)
    print(header)
    for i, d in enumerate(defender_names):
        row = f"{d:<16}" + "".join(f"{B[i, j] * 100:>15.1f}%" for j in range(len(attacker_names)))
        print(row)


def print_equilibria(defender_names, attacker_names, game, equilibria, title="내시균형"):
    print(f"\n=== {title} ===")
    for idx, (sigma_d, sigma_a) in enumerate(equilibria, start=1):
        print(f"\n[균형 {idx}]")
        print("  방어자 혼합전략:", ", ".join(
            f"{d}={p:.3f}" for d, p in zip(defender_names, sigma_d)))
        print("  공격자 혼합전략:", ", ".join(
            f"{a}={p:.3f}" for a, p in zip(attacker_names, sigma_a)))
        payoff_d, payoff_a = game[sigma_d, sigma_a]
        print(f"  균형에서의 격추율(방어자 payoff) = {payoff_d * 100:.1f}%, "
              f"누출율(공격자 payoff) = {payoff_a * 100:.1f}%")


def save_payoff_csv(defender_names, attacker_names, detail_rows, path="game_theory_payoff.csv"):
    fieldnames = ["defender", "attacker", "kill_rate", "leak_rate", "n_replications", "sim_time"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in detail_rows:
            row = dict(r)
            row["n_replications"] = N_REPLICATIONS
            row["sim_time"] = SIM_TIME
            writer.writerow(row)
    print(f"\nCSV 저장: {path}")


def save_equilibria_csv(defender_names, attacker_names, game, equilibria, path="game_theory_equilibria.csv"):
    fieldnames = (["equilibrium_id"]
                  + [f"defender_{d}" for d in defender_names]
                  + [f"attacker_{a}" for a in attacker_names]
                  + ["defender_payoff_killrate", "attacker_payoff_leakrate"])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, (sigma_d, sigma_a) in enumerate(equilibria, start=1):
            payoff_d, payoff_a = game[sigma_d, sigma_a]
            row = {"equilibrium_id": idx,
                   "defender_payoff_killrate": payoff_d,
                   "attacker_payoff_leakrate": payoff_a}
            row.update({f"defender_{d}": p for d, p in zip(defender_names, sigma_d)})
            row.update({f"attacker_{a}": p for a, p in zip(attacker_names, sigma_a)})
            writer.writerow(row)
    print(f"CSV 저장: {path}")


RISK_PERCENTILE = 95
RISK_N_REPLICATIONS = 200


if __name__ == "__main__":
    # 1) 기댓값(평균) 기반 균형
    defender_names, attacker_names, A, B, detail_rows = compute_payoff_matrix()
    print_payoff_table(defender_names, attacker_names, B, title="페이오프 행렬 - 평균 누출율 (%)")

    game = nash.Game(A, B)
    equilibria = list(game.support_enumeration())
    print_equilibria(defender_names, attacker_names, game, equilibria, title="내시균형 - 평균 기준")

    save_payoff_csv(defender_names, attacker_names, detail_rows)
    save_equilibria_csv(defender_names, attacker_names, game, equilibria)

    # 2) 리스크 회피(95퍼센타일) 기반 균형
    print(f"\n\n{'='*60}\n리스크 회피 페이오프 (P{RISK_PERCENTILE}, {RISK_N_REPLICATIONS}회 반복)\n{'='*60}")
    d_r, a_r, A_r, B_r, detail_rows_r = compute_payoff_matrix_risk(
        percentile=RISK_PERCENTILE, n_replications=RISK_N_REPLICATIONS)
    print_payoff_table(d_r, a_r, B_r, title=f"페이오프 행렬 - P{RISK_PERCENTILE} 누출율 (%)")

    game_r = nash.Game(A_r, B_r)
    equilibria_r = list(game_r.support_enumeration())
    print_equilibria(d_r, a_r, game_r, equilibria_r, title=f"내시균형 - P{RISK_PERCENTILE} 리스크 기준")

    save_payoff_csv_risk(detail_rows_r, RISK_PERCENTILE, RISK_N_REPLICATIONS)
    save_equilibria_csv(d_r, a_r, game_r, equilibria_r, path="game_theory_equilibria_risk.csv")
