"""분석 기간 단위: 반순(5일), ISO 주(월~일), 달력 월, 최근 7일, 최근 30일.

모든 단위는 (시작일, 끝일) 쌍으로 바꾼 뒤 같은 방식으로 집계한다.
기간이 자료 끝 날짜를 넘으면 "진행 중"으로 표시하고 실제로 포함된 날짜 수를 적는다.

반순 정의: 1월 1~5일이 제1반순, 연 73개. 윤년 2월 29일은 제12반순(2월 25일~3월 1일)에 넣어 그 반순만 6일이 된다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

KINDS = ("pentad", "week", "month", "last7", "last30")
KIND_LABEL = {"pentad": "반순", "week": "주", "month": "월", "last7": "최근 7일", "last30": "최근 30일"}


@dataclass(frozen=True)
class Period:
    kind: str
    start: dt.date
    end: dt.date            # 기간의 정해진 끝 (진행 중이면 자료 끝보다 뒤)
    label: str
    pid: str                # 파일 이름으로 쓰는 식별자

    def eff_end(self, data_end: dt.date) -> dt.date:
        return min(self.end, data_end)

    def n_days(self, data_end: dt.date) -> int:
        return (self.eff_end(data_end) - self.start).days + 1

    def full_days(self) -> int:
        return (self.end - self.start).days + 1

    def complete(self, data_end: dt.date) -> bool:
        return self.end <= data_end

    def info(self, data_end: dt.date) -> dict:
        d = asdict(self)
        d.update(start=str(self.start), end=str(self.end), eff_end=str(self.eff_end(data_end)),
                 n_days=self.n_days(data_end), full_days=self.full_days(), complete=self.complete(data_end),
                 kind_label=KIND_LABEL[self.kind])
        return d


# ------------------------------------------------------------------ 반순
def pentad_bounds(year: int, k: int) -> tuple[dt.date, dt.date]:
    """year년 제k반순(1~73)의 시작·끝일."""
    assert 1 <= k <= 73
    start = dt.date(year, 1, 1) + dt.timedelta(days=5 * (k - 1))
    end = start + dt.timedelta(days=4)
    leap = pd.Timestamp(year, 1, 1).is_leap_year
    if leap:
        if k > 12:
            start += dt.timedelta(days=1)
        if k >= 12:
            end += dt.timedelta(days=1)
    return start, end


def pentad_of(d: dt.date) -> tuple[int, int]:
    """날짜가 속한 (해, 반순 번호). 윤년에는 3월 1일부터 하루씩 당겨 2월 29일이 제12반순에 남게 한다."""
    doy = d.timetuple().tm_yday
    if pd.Timestamp(d).is_leap_year and doy >= 61:
        doy -= 1
    return d.year, (doy - 1) // 5 + 1


def pentad(year: int, k: int) -> Period:
    s, e = pentad_bounds(year, k)
    return Period("pentad", s, e, f"{year}년 제{k}반순 ({s:%m.%d}~{e:%m.%d})", f"pentad_{year}_{k:02d}")


# ------------------------------------------------------------------ ISO 주, 월
def week_of(d: dt.date) -> Period:
    s = d - dt.timedelta(days=d.weekday())
    e = s + dt.timedelta(days=6)
    y, w, _ = s.isocalendar()
    return Period("week", s, e, f"{y}년 {w}주 ({s:%m.%d} 월 ~ {e:%m.%d} 일)", f"week_{y}_W{w:02d}")


def month_of(d: dt.date) -> Period:
    s = d.replace(day=1)
    e = (pd.Timestamp(s) + pd.offsets.MonthEnd(0)).date()
    return Period("month", s, e, f"{s.year}년 {s.month}월", f"month_{s:%Y_%m}")


def last_n(data_end: dt.date, n: int) -> Period:
    s = data_end - dt.timedelta(days=n - 1)
    kind = {7: "last7", 30: "last30"}[n]
    return Period(kind, s, data_end, f"최근 {n}일 ({s:%m.%d}~{data_end:%m.%d})", kind)


def period_of(kind: str, d: dt.date) -> Period:
    if kind == "pentad":
        return pentad(*pentad_of(d))
    if kind == "week":
        return week_of(d)
    if kind == "month":
        return month_of(d)
    raise ValueError(kind)


def recent_periods(data_end: dt.date, counts=None) -> list[Period]:
    """자료 끝 날짜로부터 거슬러 올라가며 단위별 최근 기간 목록 (새 것이 앞)."""
    counts = counts or {"pentad": 12, "week": 8, "month": 3}
    out: list[Period] = [last_n(data_end, 7), last_n(data_end, 30)]
    for kind, n in counts.items():
        p = period_of(kind, data_end)
        seen = []
        while len(seen) < n:
            seen.append(p)
            p = period_of(kind, p.start - dt.timedelta(days=1))
        out += seen
    return out


# ------------------------------------------------------------------ 집계
def aggregate(df: pd.DataFrame | pd.Series, p: Period, data_end: dt.date, how: str = "mean"):
    sub = df[str(p.start):str(p.eff_end(data_end))]
    return sub.sum() if how == "sum" else sub.mean()


def same_dates_other_years(s: pd.Series, start: dt.date, end: dt.date, min_frac: float = 1.0) -> pd.Series:
    """해마다 같은 달·일 구간의 평균 (색인: 끝 날짜의 해). 이번 해가 마지막 원소.

    기간 비교의 기준 표본이다. 1월 1일을 걸치는 구간은 끝 날짜의 해로 묶는다.
    """
    out = {}
    first, last = s.index[0], s.index[-1]
    length = (end - start).days
    for y in range(first.year, end.year + 1):
        try:
            e = pd.Timestamp(end).replace(year=y)
        except ValueError:          # 2월 29일
            e = pd.Timestamp(y, 2, 28)
        a = e - pd.Timedelta(days=length)
        if a < first or e > last:
            continue
        seg = s[a:e]
        if seg.notna().sum() >= min_frac * (length + 1):
            out[y] = seg.mean()
    return pd.Series(out, dtype="float64")


def standing(hist: pd.Series, clim=(1991, 2020)) -> dict:
    """이번 값(hist 마지막)의 평년 기준 표준화 편차, 1979년 이후 백분위·순위."""
    now = float(hist.iloc[-1])
    base = hist[(hist.index >= clim[0]) & (hist.index <= clim[1])]
    sd = float(base.std())
    past = hist.iloc[:-1]
    pct = float((past < now).mean() * 100 + (past == now).mean() * 50) if len(past) else np.nan
    return dict(value=now, sigma=float((now - base.mean()) / sd) if sd > 0 else np.nan, percentile=pct,
                rank_high=int((hist > now).sum() + 1), n_years=int(len(hist)), year0=int(hist.index[0]))
