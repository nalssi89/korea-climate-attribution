"""기상청 API 허브에서 ASOS 일자료(평균기온, 일강수량)를 받는다.

키는 환경변수 `KMA_API_KEY`로 읽는다. 클라우드 환경에 따라 같은 키가 `KMA_AUTHKEY`라는 이름으로만
설정된 경우가 있어 그 이름도 받아 준다. 요청 주소(키 포함)와 예외 문자열은 로그에 남기지 않는다.
서버가 연결을 끊는 일이 잦아 요청마다 몇 번 다시 시도한다.
연 단위 파일로 저장하고 이미 다 받은 해는 건너뛴다 (요청 한 건의 지연이 커서 달보다 해 단위가 훨씬 빠르다).
진행 중인 해는 실행할 때마다 끝 날짜까지 다시 받는다.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time

import numpy as np
import pandas as pd
import requests

from .. import config as C
from .. import kma_official as K
from ..common import get_logger, has_key

log = get_logger("fetch.kma")
URL = f"{C.KMA_HUB}/api/typ01/url/kma_sfcdd3.php"
# kma_sfcdd3 응답의 열 순서(머리말에서 찾지 못할 때 쓰는 기본 위치)
DEFAULT_COL = {"TM": 0, "STN": 1, "TA_AVG": 10, "RN_DAY": 38}


FIELD_RE = re.compile(r"^#\s*(\d+)\.\s+([A-Z0-9_]+)\s*:")


def _field_cols(text: str) -> dict | None:
    """help=1 응답의 "# N. FIELD : 설명" 줄에서 열 위치를 찾는다 (kmahub와 같은 방식)."""
    found = sorted((int(m.group(1)), m.group(2)) for m in map(FIELD_RE.match, text.splitlines()) if m)
    names = [n for _, n in found]
    if all(k in names for k in DEFAULT_COL):
        return {k: names.index(k) for k in DEFAULT_COL}
    return None


def _parse(text: str) -> pd.DataFrame:
    fixed = _field_cols(text)
    cols = fixed or dict(DEFAULT_COL)
    rows = []
    for line in text.splitlines():
        if line.startswith("#"):
            if fixed:
                continue
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


KEY_NAMES = ("KMA_API_KEY", "KMA_AUTHKEY", "KMA_API_AUTH_KEY")  # 마지막은 kmahub에서 쓰는 이름


def key_name() -> str | None:
    """설정된 키 환경변수의 이름(값이 아님)."""
    return next((n for n in KEY_NAMES if has_key(n)), None)


def _get(params: dict, tries: int = 5) -> requests.Response:
    last = None
    for k in range(tries):
        try:
            r = requests.get(URL, timeout=300, params=params | {"authKey": os.environ[key_name()]})
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(2 * 2 ** k)
    raise RuntimeError(last)


def _year_file(y: int):
    return C.DATA / "kma" / f"asos_{y}.csv"


def run(end: dt.date) -> str:
    """돌려주는 값은 상태 문자열 (보고서에 그대로 적는다)."""
    if key_name() is None:
        return "건너뜀: 환경변수 KMA_API_KEY(또는 KMA_AUTHKEY, KMA_API_AUTH_KEY) 없음"
    got = 0
    for y in range(C.START_YEAR, end.year + 1):
        f = _year_file(y)
        complete = dt.date(y, 12, 31) <= end
        if f.exists() and complete:
            continue
        t2 = min(dt.date(y, 12, 31), end)
        try:
            r = _get({"tm1": f"{y}0101", "tm2": t2.strftime("%Y%m%d"), "stn": 0, "help": 1})
        except RuntimeError as e:   # 예외 문자열에 주소(키)가 들어갈 수 있어 종류만 남긴다
            return f"중단: KMA API 허브 요청 실패 ({e}), {got}개 해 새로 받음 (다시 실행하면 이어받음)"
        df = _parse(r.text)
        if df.empty:
            return f"중단: {y}년 응답을 해석하지 못함, {got}개 해 새로 받음"
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".csv.part")
        df.to_csv(tmp, index=False)
        tmp.rename(f)
        got += 1
        log.info("KMA ASOS %d년 받음 (%d개 지점)", y, df.stn.nunique())
    return f"완료: {got}개 해 새로 받음 (키 이름 {key_name()})"


MIN_STATIONS = 56   # 62개 중 90% 이상 관측이 있는 날만 전국 평균을 낸다


def _equal_mean(df: pd.DataFrame, ids: list[int]) -> pd.DataFrame:
    sub = df[df.stn.isin(ids)]
    g = sub.groupby("date")
    out = g[["ta", "rn"]].mean()
    n_ta, n_rn = g.ta.count(), g.rn.count()
    out.loc[n_ta < MIN_STATIONS, "ta"] = np.nan
    out.loc[n_rn < MIN_STATIONS, "rn"] = np.nan
    out["n_ta"] = n_ta
    return out


def _merged(df: pd.DataFrame) -> pd.DataFrame:
    """평년용 통합 지점(860 대구·신암, 864 전주·완산)을 만든다."""
    df = df.copy()
    for new, old, last in K.MERGE_RULES:
        last = pd.Timestamp(last)
        df = df[~((df.stn == new) & (df.date <= last))]          # 통합 지점의 이른 기록은 옛 지점으로 대신
        df.loc[(df.stn == old) & (df.date <= last), "stn"] = new
    return df


def national_daily() -> pd.DataFrame | None:
    """기상청 공식 전국(남한 내륙 62개 지점) 일평균 기온·일강수량. 자료가 없으면 None.

    kmahub와 같은 기준이다.
    - `ta`, `rn`: 대표 62개 지점(143 대구, 146 전주 포함)의 같은 가중치 평균. 실황 값.
    - `ta_norm`, `rn_norm`: 평년 계산용 62개 지점(143→860, 146→864 통합)의 같은 가중치 평균.
      편차는 `ta - 평년(ta_norm)`으로 낸다.
    - 하루에 관측이 있는 지점이 56개(90%) 미만이면 그날 전국 평균은 결측.
    """
    files = sorted((C.DATA / "kma").glob("asos_*.csv"))
    if not files:
        return None
    df = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files])
    df["stn"] = pd.to_numeric(df.stn, errors="coerce")
    rep = _equal_mean(df, K.REPRESENTATIVE_IDS)
    nor = _equal_mean(_merged(df), K.NORMAL_IDS)
    out = rep.join(nor[["ta", "rn"]].rename(columns={"ta": "ta_norm", "rn": "rn_norm"}), how="outer")
    out.attrs["n_station"] = len(K.REPRESENTATIVE_IDS)
    return out
