# 대공방어 요격 자원 배분 시뮬레이션

SimPy 기반 대공방어 요격 자원 배분 시뮬레이션. 위협 4종(탄도미사일/순항미사일/항공기/무인기)에
대해 교전 채널(발사대) N개를 우선순위 큐로 배분하는 기본 시뮬레이션에서 출발해,
shoot-look-shoot 재요격 로직, 채널 수 sweep, 그리고 방어자(채널 예약 정책) vs
공격자(위협 구성비)의 게임이론 레이어(내시균형, 리스크 회피 페이오프)까지 단계적으로 확장했다.

## 환경

```bash
conda activate simpy_env
```

필요 패키지: `simpy`, `matplotlib`, `numpy`, `pandas`, `nashpy` (모두 `simpy_env`에 설치되어 있음).
한글 그래프 출력을 위해 `Noto Sans CJK KR` 폰트를 사용한다 — 다른 머신에서 실행 시 해당 폰트가
없으면 `channel_sweep.py` 상단의 `plt.rcParams["font.family"]`를 설치된 한글 폰트로 바꿀 것.

## 실행 순서

```bash
cd /home/daniel/simpy_test
conda activate simpy_env

python air_defense_sim.py              # 1. 기본 시뮬레이션 (표적별 리포트 + CSV)
python channel_sweep.py                 # 2. 채널 수(1/2/3/5) sweep + 그래프 + CSV
python game_theory.py                   # 3. 게임이론: 평균/P95 기준 내시균형
python equilibrium_report.py            # 4. 균형점 상세(표적별) 리포트
python game_theory_multi_percentile.py  # 5. P50/P75/P90/P95 균형 비교
python game_theory_crossover_scan.py    # 6. P75~P90 구간 균형 전환점 정밀 스캔
```

각 스크립트는 독립적으로 재실행 가능하며 실행할 때마다 결과 CSV/PNG를 덮어쓴다.
`channel_sweep.py`, `game_theory.py`, `equilibrium_report.py`,
`game_theory_multi_percentile.py`, `game_theory_crossover_scan.py`는
`air_defense_sim.py`를 import하므로 같은 디렉토리에서 실행해야 한다.

## 1. 기본 시뮬레이션 — `air_defense_sim.py`

- `simpy.PriorityResource(capacity=NUM_CHANNELS)`로 교전 채널을 자원화 (기본 3개)
- 위협 4종은 `THREATS` 딕셔너리에 우선순위(`priority`, 낮을수록 우선)·평균 발생 간격
  (`mean_interarrival`)·교전 시간(`engagement_time`)·격추확률(`pk`)·재장전 시간
  (`reload_time`)·재요격 허용 횟수(`max_shots`)로 정의되어 있다.
- **shoot-look-shoot(SLS)**: 탄도미사일/순항미사일(`max_shots=3`)은 1차 요격이 실패해도
  원래 채널의 재장전을 기다리지 않고 즉시 잔여 채널로 재요격을 시도한다. 재장전은
  `_reload_and_release()`로 분리된 백그라운드 프로세스라서, 표적의 재요격 판단이 재장전
  완료를 기다리지 않는다. 항공기/무인기는 재요격 없음(`max_shots=1`).
- **누출(leak) 정의**: `발생 - 격추`. 교전 후 격추 실패(Pk 미스)뿐 아니라, 채널 부족으로
  시뮬레이션 종료 시까지 사격 기회 자체를 못 받은 표적(미교전)도 방어 관점에서는 "통과"이므로
  누출로 집계한다. (초기 버전에는 미교전을 누출에서 빠뜨리는 버그가 있었고, 채널 수 sweep에서
  격추율+누출율 합이 100%가 안 되는 걸 보고 발견해 수정했다.)
- 실행 시 표적별 발생/교전/격추/교전실패/미교전/재요격 횟수와 평균 대기시간을 콘솔에 출력하고
  `simulation_report.csv`로 저장한다 (재현을 위해 채널 수/시뮬레이션 시간/시드 포함).

## 2. 채널 수 Sweep — `channel_sweep.py`

- `NUM_CHANNELS_LIST = [1, 2, 3, 5]` 각각에 대해 서로 다른 시드로 30회 반복 실행 후 평균.
- 격추율/누출율, 평균 대기시간을 `channel_sweep.png`로 시각화 (matplotlib, 한글 폰트,
  dataviz 스킬의 검증된 팔레트 사용).
- `channel_sweep_summary.csv`(채널당 요약), `channel_sweep_raw.csv`(반복별 원본 데이터,
  120행) 저장.
- 관찰: 채널 1개는 병목이 심각(대기시간 급증, 누출율 높음)하지만 3개부터는 격추율이
  정체(diminishing returns) — 이 위협 발생률 시나리오에서는 채널 5개가 자원 낭비일 수 있음.

## 3~6. 게임이론 레이어

`air_defense_sim.py`의 시뮬레이션을 "페이오프 오라클"로 두고, 방어자와 공격자를 각각
이산 전략 집합으로 정의해 **empirical game-theoretic analysis(EGTA)** 방식으로 접근한다:
전략 조합마다 시뮬레이션을 반복해 페이오프 행렬을 채우고, 그 행렬 위에서 `nashpy`로
내시균형을 계산한다. 시뮬레이션(확률적 결과)과 게임이론(전략적 균형)은 대체 관계가 아니라
레이어 관계 — 게임이론은 시뮬레이션 반복의 집계값을 입력으로 받아 그 위에서 균형을 푼다.

### 전략 공간 (`game_theory.py`)

- **방어자**: 총 3채널 중 고우선순위(탄도미사일+순항미사일) 전용으로 예약할 채널 수 K.
  `D0_무예약(K=0)` / `D1_1채널예약(K=1)` / `D2_2채널예약(K=2)`.
  구현은 예약 채널 풀(reserved)과 공용 채널 풀(shared) 두 개로 분리하고, 고우선순위 표적은
  두 풀에 동시에 요청을 건 뒤 먼저 허가되는 쪽을 사용한다(`_fire_shot_reserved`). 둘 다 같은
  시점에 허가되면 하나는 즉시 반납(`release`), 미허가 쪽은 취소(`cancel`)해서 자원이 새지
  않도록 처리했다 — SimPy 소스(`Put.cancel()`/`Resource.release()`가 동기적으로 동작함)를
  직접 확인하고 구현.
- **공격자**: 총 공격 예산(발생률 총합)은 베이스라인과 동일하게 고정하고, 4개 위협 유형에
  대한 구성비만 다르게 배분. `A1_균형`(25%씩 균등) / `A2_무인기포화`(무인기 70%) /
  `A3_고가치집중`(탄도+순항 75%).
- **페이오프**: 방어자=격추율, 공격자=누출율 (매 반복에서 `kill_rate + leak_rate = 1`인
  constant-sum 구조).

### 평균 vs 리스크 회피(percentile) 페이오프

- `compute_payoff_matrix()`: 각 셀 30회 반복의 **평균** 누출율을 페이오프로 사용.
- `compute_payoff_matrix_risk(percentile, n_replications)`: 각 셀의 누출율 **percentile**
  (예: P95 = "최악에 가까운 5% 시나리오")을 페이오프로 사용. percentile 추정은 표본이 많이
  필요해 반복 횟수를 30 → 200으로 늘렸다.
- **평균 기준 균형**: D0(무예약) vs A2(무인기포화), 누출율 31.4%
- **P95 기준 균형**: D1(1채널예약) vs A2(무인기포화), 누출율 42.4%
- 공격자의 지배전략은 항상 A2(무인기포화) — 무인기는 Pk가 낮고(0.60) 재요격도 없어서,
  "고가치 표적 집중" 공격보다 훨씬 효과적이다. 방어자 쪽만 평균/리스크 기준에 따라
  D0 ↔ D1 사이에서 바뀐다: 채널 예약은 평균 처리량에는 거의 도움이 안 되지만, 운 나쁜
  꼬리 시나리오(트래픽이 몰리는 경우)에서는 고우선순위 표적에 최소 1채널을 보장해줘서
  리스크를 줄여준다.

### 전환점 스캔 (`game_theory_multi_percentile.py`, `game_theory_crossover_scan.py`)

- P50/P75/P90/P95 네 수준을 비교한 결과 균형은 D0(P50, P75)에서 D1(P90, P95)로 바뀐다.
- P75~P90 구간을 0.5 단위로 정밀 스캔한 결과 **전환점은 P77.5~P78.0 사이(선형보간
  약 P77.89)**. 즉 "상위 25% 이상의 나쁜 시나리오까지 대비하고 싶다"는 리스크 회피 성향부터
  채널 예약이 정당화된다.
- 이 스캔은 셀당 200개 표본을 한 번만 뽑아 percentile 값만 이동시키며 재사용한다
  (시뮬레이션 재실행 없이 `np.percentile` 보간만 사용). 표본이 200개뿐이라 percentile
  추정에는 표집오차가 있으므로, 소수점까지 정확한 값이 아니라 "P77~78 근방"으로 해석해야
  한다.

### 균형점 상세 리포트 (`equilibrium_report.py`)

- 균형은 전략 공간 위의 해(solution concept)라서 이론적으로는 재시뮬레이션이 불필요하지만,
  균형이 실제로 어떤 시나리오인지 감을 잡기 위해 균형점(D0×A2, D1×A2)에서 단일 실행
  (seed=0)을 하나씩 돌려 표적별 상세 리포트를 생성한다.
- **주의**: 단일 실행 값은 표본 하나일 뿐이라 균형 계산에 쓰인 집계값(평균/P95)과 다를 수
  있다(변동성 자체가 정상). 혼동을 막기 위해 콘솔 출력과 CSV 모두에 "이 값은 단일 실행
  결과이며, 같은 전략 조합을 N=200회 반복한 집계 기준값(평균/P95/범위/표준편차)은 별도"라는
  주석을 명시했다.

## 출력 파일 요약

| 파일 | 생성 스크립트 | 내용 |
|---|---|---|
| `simulation_report.csv` | `air_defense_sim.py` | 단일 실행, 표적별 상세 결과 |
| `channel_sweep.png` | `channel_sweep.py` | 채널 수별 격추율/누출율/대기시간 그래프 |
| `channel_sweep_summary.csv` | `channel_sweep.py` | 채널 수별 요약(30회 평균) |
| `channel_sweep_raw.csv` | `channel_sweep.py` | 채널×시드 반복별 원본 데이터 |
| `game_theory_payoff.csv` | `game_theory.py` | 평균 기준 페이오프 행렬(3×3) |
| `game_theory_equilibria.csv` | `game_theory.py` | 평균 기준 내시균형 |
| `game_theory_payoff_risk.csv` | `game_theory.py` | P95 기준 페이오프 행렬 |
| `game_theory_equilibria_risk.csv` | `game_theory.py` | P95 기준 내시균형 |
| `equilibrium_report_*.csv` | `equilibrium_report.py` | 균형점 단일 실행 상세 리포트 + 집계 기준값 주석 |
| `game_theory_equilibria_by_percentile.csv` | `game_theory_multi_percentile.py` | P50/75/90/95 균형 비교 |
| `game_theory_crossover_scan.csv` | `game_theory_crossover_scan.py` | P75~P90 0.5 단위 균형 전환 스캔 |

## 파라미터 수정 위치

- 위협 특성(우선순위/Pk/재장전시간/재요격 횟수): `air_defense_sim.py`의 `THREATS`
- 채널 수 sweep 구간/반복 횟수: `channel_sweep.py`의 `NUM_CHANNELS_LIST`, `N_REPLICATIONS`
- 방어자/공격자 전략 정의: `game_theory.py`의 `DEFENDER_STRATEGIES`, `ATTACKER_STRATEGIES`
- 리스크 percentile/반복 횟수: `game_theory.py`의 `RISK_PERCENTILE`, `RISK_N_REPLICATIONS`
