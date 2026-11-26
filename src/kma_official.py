"""기상청 공식 전국(남한 내륙) 62개 지점 기준과 1991~2020 평년비슷범위.

사용자의 kmahub 저장소(`src/normalCriteria.js`)와 같은 기준을 쓴다.
- 대표 지점: 제주를 뺀 남한 내륙 62개 지점, 지점 간 같은 가중치로 평균한다.
- 평년(1991~2020) 계산에는 대구(143)와 전주(146) 대신 통합 지점 860(대구·신암), 864(전주·완산)을 쓴다.
  860: 143(1991-01-01~2015-06-11) + 860(2015-06-12~), 864: 146(1991-01-01~2015-06-30) + 864(2015-07-01~)
- 평년비슷범위: 기온은 평년 ± 0.43σ(공식 발표값), 강수는 33~67 백분위(공식 발표값).
- 판정은 공식 발표 기준값을 그대로 쓴다(재계산하지 않음).
"""
from __future__ import annotations

import datetime as dt

REPRESENTATIVE_IDS = [
    108, 112, 119, 201, 202, 203,
    90, 105, 100, 216,
    211, 95, 101, 212, 114,
    131, 127, 226, 135, 221,
    133, 232, 129, 235, 236, 238,
    143, 281, 138, 279, 278, 136, 273, 272, 277, 130, 271,
    159, 152, 284, 285, 289, 288, 295, 192, 155, 162, 294,
    146, 243, 245, 140, 247, 244, 248,
    156, 165, 261, 260, 170, 262, 168,
]
NORMAL_IDS = [860 if s == 143 else 864 if s == 146 else s for s in REPRESENTATIVE_IDS]

# (통합 지점, 옛 지점, 옛 지점 마지막 날)
MERGE_RULES = [
    (860, 143, dt.date(2015, 6, 11)),
    (864, 146, dt.date(2015, 6, 30)),
]

# 공식 1991~2020 전국 62개 지점 월별 평년값과 평년비슷범위
CRITERIA = {
    "tavg": dict(
        normal=[-0.9, 1.2, 6.1, 12.1, 17.3, 21.4, 24.6, 25.1, 20.5, 14.3, 7.6, 1.1],
        half=[0.6, 0.6, 0.5, 0.5, 0.3, 0.3, 0.6, 0.5, 0.3, 0.4, 0.6, 0.6],
    ),
    "precip": dict(
        normal=[26.2, 35.7, 56.5, 89.7, 102.1, 148.2, 296.5, 282.6, 155.1, 63.0, 48.0, 28.0],
        lower=[17.4, 27.5, 42.7, 70.3, 79.3, 101.6, 245.9, 225.3, 84.2, 37.0, 30.7, 19.8],
        upper=[26.8, 44.9, 58.5, 99.3, 125.5, 174.0, 308.2, 346.7, 202.3, 64.3, 55.1, 28.6],
    ),
}


def _r1(x: float) -> float:
    """kmahub와 같은 반올림(소수 첫째 자리, 0.5 올림)."""
    import math
    return math.floor(x * 10 + 0.5 + 1e-9) / 10


def classify_tavg(month: int, observed: float) -> dict:
    c = CRITERIA["tavg"]
    normal, half = c["normal"][month - 1], c["half"][month - 1]
    dep = _r1(_r1(observed) - normal)
    sign = "-" if dep < -half else "+" if dep > half else "0"
    word = {"-": "낮음", "0": "비슷", "+": "높음"}[sign]
    return dict(observed=_r1(observed), normal=normal, departure=dep, half_range=half,
                lower=_r1(normal - half), upper=_r1(normal + half), sign=sign, word=word)


def classify_precip(month: int, observed: float) -> dict:
    c = CRITERIA["precip"]
    v = _r1(observed)
    lo, hi = c["lower"][month - 1], c["upper"][month - 1]
    sign = "-" if v < lo else "+" if v > hi else "0"
    word = {"-": "적음", "0": "비슷", "+": "많음"}[sign]
    return dict(observed=v, normal=c["normal"][month - 1], ratio=v / c["normal"][month - 1] * 100,
                lower=lo, upper=hi, sign=sign, word=word)
