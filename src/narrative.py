"""수치에서 문장을 만드는 규칙 (객관 분석 원칙).

모든 서술은 계산된 값에서 나온다. 규칙은 여기 한곳에 모아 보고서와 대시보드가 같은 말을 쓰게 한다.
- |σ| ≥ 1.5: "뚜렷하게 높음/낮음", 0.5 ≤ |σ| < 1.5: "다소 높음/낮음", |σ| < 0.5: "평년 수준"
- 부트스트랩 5~95% 구간이 0을 포함하면 "유의하지 않음", 포함하지 않으면 "유의함"
- 교차검증 R² < 0.1: "설명력 낮음", 0.1~0.3: "설명력 보통", ≥ 0.3: "설명력 높음"
"""
from __future__ import annotations

import math

from . import config as C


def sigma_word(z: float, hi: str = "높음", lo: str = "낮음") -> str:
    if z is None or not math.isfinite(z):
        return "판정 불가"
    if abs(z) >= C.SIGMA_STRONG:
        return f"뚜렷하게 {hi if z > 0 else lo}"
    if abs(z) >= C.SIGMA_WEAK:
        return f"다소 {hi if z > 0 else lo}"
    return "평년 수준"


def temp_word(z: float) -> str:
    return sigma_word(z, "따뜻함", "추움")


def precip_word(z: float) -> str:
    return sigma_word(z, "많음", "적음")


def ci_word(lo: float, hi: float) -> str:
    return "유의함" if (lo > 0 or hi < 0) else "유의하지 않음"


def r2_word(r2: float) -> str:
    if r2 is None or not math.isfinite(r2):
        return "판정 불가"
    return "설명력 낮음" if r2 < 0.1 else ("설명력 보통" if r2 < 0.3 else "설명력 높음")


def num(v: float, nd: int = 1, unit: str = "", sign: bool = True) -> str:
    if v is None or not math.isfinite(v):
        return "–"
    return f"{v:+.{nd}f}{unit}" if sign else f"{v:.{nd}f}{unit}"


def standing_phrase(st: dict, unit: str = "", nd: int = 1) -> str:
    """'+1.2°C (+1.6σ, 1979년 이후 같은 날짜 48개 해 중 높은 순 3위)'"""
    return (f"{num(st['value'], nd, unit)} ({num(st['sigma'], 1, 'σ')}, {st['year0']}년 이후 같은 날짜 "
            f"{st['n_years']}개 해 중 높은 순 {st['rank_high']}위)")


def contribution_sentence(name: str, res: dict, unit: str) -> str:
    """회귀 기여도 한 줄 요약. 유의한 인자만 이름을 들고, 설명력 등급을 붙인다."""
    sig = [f for f in res["factors"] if f["lo"] > 0 or f["hi"] < 0]
    sig.sort(key=lambda f: -abs(f["contribution"]))
    head = (f"{name} 관측 편차 {num(res['observed'], 2, unit)} 중 회귀로 설명된 몫은 {num(res['predicted'], 2, unit)}, "
            f"잔차 {num(res['residual'], 2, unit)} (교차검증 R² {res['r2_cv']:.2f}, {r2_word(res['r2_cv'])}).")
    if sig:
        head += " 신뢰구간이 0을 벗어난 인자: " + ", ".join(
            f"{f['label']} {num(f['contribution'], 2, unit)}" for f in sig) + "."
    else:
        head += " 신뢰구간이 0을 벗어난 인자는 없다."
    return head


def josa(word: str, pair: str) -> str:
    """받침에 따라 조사를 고른다. pair = "은/는", "이/가", "와/과", "을/를". 괄호 속 설명은 빼고 마지막 글자로 판단한다."""
    import re
    w = re.sub(r"\([^)]*\)\s*$", "", word).strip() or word
    a, b = pair.split("/")          # a: 받침 있을 때, b: 없을 때 (와/과는 반대)
    if pair == "와/과":
        a, b = "과", "와"
    c = w[-1]
    if "가" <= c <= "힣":
        has = (ord(c) - 0xAC00) % 28 != 0
    else:                            # 숫자·로마자: 읽는 소리의 받침 (0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔, L 엘, M 엠, N 엔, R 알)
        has = c in "013678LMNRlmnr"
    return word + (a if has else b)
