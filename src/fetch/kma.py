"""기상청 API 허브에서 ASOS 일자료(평균기온, 일강수량)를 받는다.

주의: `KMA_API_KEY`가 없고 apihub.kma.go.kr이 막힌 환경에서 작성돼 실제 응답으로 검증하지 못했다.
키는 환경변수로만 읽고, 요청 주소(키 포함)는 로그에 남기지 않는다.
월 단위 파일로 저장하고 이미 있는 달은 건너뛴다.
"""
from __future__ import annotations

import datetime as dt
import io
import os

import numpy as np
import pandas as pd
import requests

from .. import config as C
from ..common import get_logger, has_key

log = get_logger("fetch.kma")
URL = f"{C.KMA_HUB}/api/typ01/url/kma_sfcdd3.php"
# kma_sfcdd3 응답의 열 순서(머리말에서 찾지 못할 때 쓰는 기본 위치)
DEFAULT_COL = {"TM": 0, "STN": 1, "TA_AVG": 10, "RN_DAY": 38}


def _parse(text: str) -> pd.DataFrame:
    cols = dict(DEFAULT_COL)
    rows = []
    for line in text.splitlines():
        if line.startswith("#"):
            tok = line.lstrip("#").split()
            if "TA_AVG" in tok and "RN_DAY" in tok:
                cols = {k: tok.index(k) for k in DEFAULT_COL if k in tok} | \
                       {k: v for k, v in DEFAULT_COL.items() if k not in tok}
            continue
        p = line.replace(",", " ").split()
        if len(p) > max(cols.values()):
            rows.append((p[cols["TM"]], p[cols["STN"]], p[cols["TA_AVG"]], p[cols["RN_DAY"]]))
    df = pd.DataFrame(rows, columns=["date", "stn", "ta", "rn"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for c in ("ta", "rn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.loc[df.ta < -90, "ta"] = np.nan          # 결측 부호(-99 등)
    df.loc[df.rn < 0, "rn"] = 0.0               # 무강수는 -9로 온다
    return df.dropna(subset=["date"])


def _month_file(y: int, m: int):
    return C.DATA / "kma" / f"asos_{y}{m:02d}.csv"


def run(end: dt.date) -> str:
    """돌려주는 값은 상태 문자열 (보고서에 그대로 적는다)."""
    if not has_key("KMA_API_KEY"):
        return "건너뜀: 환경변수 KMA_API_KEY 없음"
    months = pd.period_range(f"{C.START_YEAR}-01", end.strftime("%Y-%m"), freq="M")
    got = 0
    for p in months:
        f = _month_file(p.year, p.month)
        complete = p.end_time.date() <= end
        if f.exists() and complete:
            continue
        t2 = min(p.end_time.date(), end)
        try:
            r = requests.get(URL, timeout=120, params={
                "tm1": f"{p.year}{p.month:02d}01", "tm2": t2.strftime("%Y%m%d"), "stn": 0, "help": 0,
                "authKey": os.environ["KMA_API_KEY"]})
            r.raise_for_status()
        except requests.RequestException as e:   # 예외 문자열에 주소(키)가 들어갈 수 있어 종류만 남긴다
            return f"중단: KMA API 허브 요청 실패 ({type(e).__name__}), {got}개월 새로 받음"
        df = _parse(r.text)
        if df.empty:
            return f"중단: {p} 응답을 해석하지 못함, {got}개월 새로 받음"
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".csv.part")
        df.to_csv(tmp, index=False)
        tmp.rename(f)
        got += 1
    return f"완료: {got}개월 새로 받음"


def national_daily() -> pd.DataFrame | None:
    """받아 둔 ASOS 자료로 전국 평균 일기온·일강수를 만든다. 자료가 없으면 None.

    기상청 공식 전국 평균(62개 지점)과 달리, 평년 기간 자료가 90% 이상 있는 지점을 자료에서 골라 평균한다.
    """
    files = sorted((C.DATA / "kma").glob("asos_*.csv"))
    if not files:
        return None
    df = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files])
    base = df[(df.date.dt.year >= C.CLIM[0]) & (df.date.dt.year <= C.CLIM[1])]
    ndays = base.date.nunique()
    if ndays == 0:
        return None
    cnt = base.dropna(subset=["ta"]).groupby("stn").date.nunique()
    keep = cnt[cnt >= 0.9 * ndays].index
    sub = df[df.stn.isin(keep)]
    out = sub.groupby("date")[["ta", "rn"]].mean()
    out.attrs["n_station"] = len(keep)
    return out
