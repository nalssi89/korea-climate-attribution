"""NOAA CPC 공식 ONI를 받아 자체 계산값과 교차 확인한다 (닿지 않으면 건너뜀)."""
from __future__ import annotations

import pandas as pd
import requests

from .. import config as C

URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def run() -> str:
    out = C.DATA / "noaa" / "oni.csv"
    try:
        r = requests.get(URL, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        return f"건너뜀: cpc.ncep.noaa.gov에 닿지 않음 ({type(e).__name__})"
    rows = []
    for line in r.text.splitlines()[1:]:
        p = line.split()
        if len(p) == 4 and p[0] in SEASONS:
            # 3개월 평균의 가운데 달로 날짜를 붙인다
            rows.append((pd.Timestamp(int(p[1]), SEASONS.index(p[0]) + 1, 1), float(p[3])))
    if not rows:
        return "건너뜀: ONI 파일 형식을 해석하지 못함"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["month", "oni_noaa"]).to_csv(out, index=False)
    return f"완료: {len(rows)}개월"
