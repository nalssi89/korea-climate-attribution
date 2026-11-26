"""우랄블로킹: Z500 역전 지수(Tibaldi-Molteni 방식)와 영역 편차, 지속 사건 탐지."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import area_mean, series_anom

# 1.5° 격자에 맞춘 기준 위도 (원래 80/60/40°N, 이동폭 ±4°)
PHI_N, PHI_0, PHI_S, DELTAS = 79.5, 60.0, 40.5, (-4.5, 0.0, 4.5)


def reversal(z500: xr.DataArray) -> xr.DataArray:
    """경도별 블로킹 여부 (time, lon). 남쪽 경도(GHGS)가 역전되고 북쪽(GHGN)이 강한 서풍일 때."""
    blocked = None
    for d in DELTAS:
        zn, z0, zs = (z500.sel(lat=p + d) for p in (PHI_N, PHI_0, PHI_S))
        ghgs = (z0 - zs) / (PHI_0 - PHI_S)
        ghgn = (zn - z0) / (PHI_N - PHI_0)
        b = (ghgs > 0) & (ghgn < C.BLOCK_GHGN)
        blocked = b if blocked is None else (blocked | b)
    return blocked


def sector_flag(blocked: xr.DataArray, west: float, east: float) -> pd.DataFrame:
    """경도대 안에서 연속으로 막힌 최대 폭(도)과 블로킹일 여부."""
    sub = blocked.sel(lon=slice(west, east)).values
    dlon = float(blocked.lon[1] - blocked.lon[0])
    run = np.zeros(sub.shape[0])
    cur = np.zeros(sub.shape[0])
    for j in range(sub.shape[1]):
        cur = np.where(sub[:, j], cur + 1, 0)
        run = np.maximum(run, cur)
    width = run * dlon
    return pd.DataFrame({"block_width": width, "blocked": width >= C.BLOCK_MIN_LON},
                        index=pd.DatetimeIndex(blocked.time.values))


def find_events(flag: pd.Series, strength: pd.Series, min_days: int = C.BLOCK_MIN_DAYS) -> pd.DataFrame:
    """연속 블로킹일이 min_days 이상이면 사건. 시작일, 끝일, 지속일, 최성일, 평균·최대 편차."""
    v = flag.values.astype(bool)
    edges = np.flatnonzero(np.diff(np.r_[False, v, False].astype(int)))
    rows = []
    for a, b in zip(edges[::2], edges[1::2]):
        if b - a >= min_days:
            seg = strength.iloc[a:b]
            rows.append(dict(onset=flag.index[a].date(), end=flag.index[b - 1].date(), duration=b - a,
                             peak=seg.idxmax().date(), mean_anom=round(float(seg.mean()), 1),
                             max_anom=round(float(seg.max()), 1)))
    return pd.DataFrame(rows)


def compute(z500: xr.DataArray) -> tuple[pd.DataFrame, pd.DataFrame]:
    w, e = C.REGIONS["ural_sector"][2:]
    df = sector_flag(reversal(z500), w, e)
    df["ural"] = series_anom(area_mean(z500, C.REGIONS["ural"]).to_series())
    events = find_events(df["blocked"], df["ural"])
    return df[["ural", "blocked", "block_width"]], events
