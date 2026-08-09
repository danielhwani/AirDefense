"""
대공방어 요격 자원 배분 시뮬레이션 (SimPy 기반)

- simpy.PriorityResource로 교전 채널(발사대) N개를 자원화
- 위협 4종(탄도미사일/순항미사일/항공기/무인기): 우선순위/발생빈도/교전시간/격추확률(Pk)이 다름
- 교전 후에도 재장전 시간 동안 채널을 계속 점유
- 고우선순위 표적(탄도미사일/순항미사일)은 1차 요격 실패 시 원래 채널의 재장전을
  기다리지 않고 잔여 채널로 즉시 재요격(shoot-look-shoot)
"""

import csv
import random
import simpy


# ----------------------------
# 시뮬레이션 파라미터
# ----------------------------
RANDOM_SEED = 42
SIM_TIME = 240          # 시뮬레이션 총 시간 (분)
NUM_CHANNELS = 3        # 교전 채널(발사대) 수

# 위협 유형별 파라미터
# priority: 낮을수록 우선순위 높음 (SimPy PriorityResource 규칙)
THREATS = {
    "탄도미사일": {
        "priority": 0,
        "mean_interarrival": 40.0,  # 평균 발생 간격 (분)
        "engagement_time": 2.0,     # 교전(요격) 소요 시간 (분)
        "pk": 0.85,                 # 격추 확률
        "reload_time": 5.0,         # 재장전 시간 (분), 채널 계속 점유
        "max_shots": 3,             # shoot-look-shoot: 1차 실패 시 재요격 허용 횟수(최대 사격 수)
    },
    "순항미사일": {
        "priority": 1,
        "mean_interarrival": 25.0,
        "engagement_time": 1.5,
        "pk": 0.80,
        "reload_time": 4.0,
        "max_shots": 3,
    },
    "항공기": {
        "priority": 2,
        "mean_interarrival": 15.0,
        "engagement_time": 3.0,
        "pk": 0.70,
        "reload_time": 6.0,
        "max_shots": 1,             # 재요격 없음
    },
    "무인기": {
        "priority": 3,
        "mean_interarrival": 8.0,
        "engagement_time": 1.0,
        "pk": 0.60,
        "reload_time": 2.0,
        "max_shots": 1,             # 재요격 없음
    },
}


class Stats:
    """시뮬레이션 결과 집계용 컨테이너"""

    def __init__(self):
        self.generated = {name: 0 for name in THREATS}
        self.engaged = {name: 0 for name in THREATS}
        self.killed = {name: 0 for name in THREATS}
        self.missed = {name: 0 for name in THREATS}    # 모든 사격(재요격 포함) 소진 후에도 격추 실패
        self.shots_fired = {name: 0 for name in THREATS}
        self.reengagements = {name: 0 for name in THREATS}  # 2차 이후 재요격 횟수
        self.wait_times = {name: [] for name in THREATS}   # 1차 사격까지의 대기시간만 기록

    def summary(self):
        """
        누출(leak) = 격추 실패(missed) + 미교전(unengaged, 채널 부족으로 시뮬레이션
        종료 시점까지 사격조차 못 받은 표적). 방어 관점에서는 둘 다 '통과'이므로
        total_leaked = generated - killed 로 정의한다.
        """
        rows = []
        for name in THREATS:
            gen = self.generated[name]
            eng = self.engaged[name]
            kill = self.killed[name]
            missed = self.missed[name]
            unengaged = gen - eng
            total_leaked = gen - kill  # missed + unengaged + (교전 중 시뮬레이션 종료로 미해결)
            avg_wait = sum(self.wait_times[name]) / len(self.wait_times[name]) if self.wait_times[name] else 0.0
            kill_rate = kill / gen if gen else 0.0
            leak_rate = total_leaked / gen if gen else 0.0
            rows.append({
                "threat": name,
                "generated": gen,
                "engaged": eng,
                "killed": kill,
                "missed": missed,
                "unengaged": unengaged,
                "leaked": total_leaked,
                "kill_rate": kill_rate,
                "leak_rate": leak_rate,
                "avg_wait": avg_wait,
                "shots_fired": self.shots_fired[name],
                "reengagements": self.reengagements[name],
            })
        return rows


def _fire_shot(env, params, channels):
    """
    사격 1회: 채널 획득 -> 교전 -> 명중 판정.
    재장전은 별도 백그라운드 프로세스로 분리해 채널을 계속 점유시키되,
    표적의 재요격 여부 판단(호출 측)은 재장전을 기다리지 않고 즉시 진행한다.
    반환값: (명중 여부, 채널 획득까지 대기시간)
    """
    req = channels.request(priority=params["priority"])
    request_time = env.now
    yield req
    wait = env.now - request_time

    yield env.timeout(params["engagement_time"])
    hit = random.random() < params["pk"]

    env.process(_reload_and_release(env, channels, req, params["reload_time"]))
    return hit, wait


def _reload_and_release(env, channels, req, reload_time):
    """재장전 시간 동안 채널을 점유한 뒤 반납"""
    yield env.timeout(reload_time)
    channels.release(req)


def threat_process(env, name, params, channels, stats):
    """
    개별 표적(위협) 하나의 생명주기: 발생 -> 채널 요청 -> 교전 -> (실패 시, 허용된
    표적에 한해) 잔여 채널로 즉시 재요격을 max_shots회까지 반복.
    """
    stats.generated[name] += 1
    killed = False

    for shot_num in range(1, params["max_shots"] + 1):
        hit, wait = yield env.process(_fire_shot(env, params, channels))
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


def threat_generator(env, name, params, channels, stats):
    """포아송 과정(지수분포 간격)으로 위협을 계속 생성"""
    while True:
        yield env.timeout(random.expovariate(1.0 / params["mean_interarrival"]))
        env.process(threat_process(env, name, params, channels, stats))


def run_simulation(num_channels=NUM_CHANNELS, sim_time=SIM_TIME, seed=RANDOM_SEED):
    random.seed(seed)
    env = simpy.Environment()
    channels = simpy.PriorityResource(env, capacity=num_channels)
    stats = Stats()

    for name, params in THREATS.items():
        env.process(threat_generator(env, name, params, channels, stats))

    env.run(until=sim_time)
    return stats


def print_report(stats, num_channels):
    rows = stats.summary()
    total_gen = sum(r["generated"] for r in rows)
    total_kill = sum(r["killed"] for r in rows)
    total_leak = sum(r["leaked"] for r in rows)
    total_missed = sum(r["missed"] for r in rows)
    total_unengaged = sum(r["unengaged"] for r in rows)
    total_reengagements = sum(r["reengagements"] for r in rows)

    print(f"\n=== 대공방어 시뮬레이션 결과 (채널 수 = {num_channels}) ===")
    header = (f"{'위협':<8}{'발생':>6}{'교전':>6}{'격추':>6}{'교전실패':>8}{'미교전':>8}"
              f"{'누출(계)':>8}{'격추율':>8}{'누출율':>8}{'평균대기':>10}{'재요격':>8}")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['threat']:<8}{r['generated']:>6}{r['engaged']:>6}{r['killed']:>6}{r['missed']:>8}"
              f"{r['unengaged']:>8}{r['leaked']:>8}"
              f"{r['kill_rate']*100:>7.1f}%{r['leak_rate']*100:>7.1f}%{r['avg_wait']:>10.2f}{r['reengagements']:>8}")
    print("-" * len(header))
    overall_kill_rate = total_kill / total_gen if total_gen else 0.0
    overall_leak_rate = total_leak / total_gen if total_gen else 0.0
    print(f"전체: 발생={total_gen}, 격추={total_kill} ({overall_kill_rate*100:.1f}%), "
          f"누출={total_leak} ({overall_leak_rate*100:.1f}%) "
          f"[교전실패={total_missed}, 미교전={total_unengaged}, 재요격={total_reengagements}]")


def save_report_csv(stats, num_channels, sim_time, seed, path="simulation_report.csv"):
    """표적별 상세 결과 + 재현에 필요한 파라미터(채널 수/시뮬레이션 시간/시드)를 CSV로 저장"""
    fieldnames = ["threat", "num_channels", "sim_time", "seed", "generated", "engaged",
                  "killed", "missed", "unengaged", "leaked", "kill_rate", "leak_rate",
                  "avg_wait", "shots_fired", "reengagements"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in stats.summary():
            row = dict(r)
            row["num_channels"] = num_channels
            row["sim_time"] = sim_time
            row["seed"] = seed
            writer.writerow(row)
    print(f"CSV 저장: {path}")


if __name__ == "__main__":
    stats = run_simulation()
    print_report(stats, NUM_CHANNELS)
    save_report_csv(stats, NUM_CHANNELS, SIM_TIME, RANDOM_SEED)
