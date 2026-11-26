"""연결 고리 인자: AO, 시베리아 고기압, 동아시아 제트, 겨울몬순 지수, 필리핀해 고기압, 바렌츠-카라 해빙."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import anomaly, area_mean, daily_clim, series_anom


def ao_index(msl: xr.DataArray) -> pd.Series:
    """북극진동: 20°N 이북 월평균 해면기압 편차의 제1 EOF에 일별 편차를 투영한다.

    부호는 북극 기압이 낮을 때 양(+). 평년 기간의 일별 표준편차로 나눈다.
    """
    sub = msl.sel(lat=slice(20, 90))
    anom = anomaly(sub, daily_clim(sub))
    w = np.sqrt(np.cos(np.deg2rad(np.clip(anom.lat, None, 89.0))))
    x = (anom * w).values.reshape(anom.sizes["time"], -1)
    t = pd.DatetimeIndex(anom.time.values)
    base = (t.year >= C.START_YEAR) & (t.year <= C.CLIM[1])
    mon = pd.DataFrame(x[base]).groupby([t[base].year, t[base].month]).mean().values
    mon = mon - mon.mean(0)
    _, _, vt = np.linalg.svd(mon, full_matrices=False)
    eof = vt[0]
    arctic = (np.repeat(anom.lat.values, anom.sizes["lon"]) >= 70)
    if eof[arctic].mean() > 0:
        eof = -eof
    pc = pd.Series(x @ eof, index=t)
    return (pc / pc[f"{C.CLIM[0]}":f"{C.CLIM[1]}"].std()).rename("ao")


def compute(msl: xr.DataArray, u200: xr.DataArray, u300: xr.DataArray, ci: xr.DataArray) -> pd.DataFrame:
    R = C.REGIONS
    out = pd.DataFrame({"ao": ao_index(msl)})
    out["siberian_high"] = series_anom(area_mean(msl, R["siberian_high"]).to_series())
    out["phil_sea"] = series_anom(area_mean(msl, R["phil_sea"]).to_series())
    out["ea_jet"] = series_anom(area_mean(u200, R["ea_jet"]).to_series())
    eawm = area_mean(u300, R["eawm_south"]) - area_mean(u300, R["eawm_north"])      # Jhun & Lee (2004)
    out["eawm"] = series_anom(eawm.to_series())
    out["bk_ice"] = series_anom(area_mean(ci, R["bk_ice"]).to_series())
    return out


def aleutian(msl: xr.DataArray) -> pd.Series:
    """알류샨 저기압 세기: 40~60°N, 160°E~140°W 해면기압 편차 (음이면 저기압이 깊음)."""
    return series_anom(area_mean(msl, C.ALEUTIAN).to_series()).rename("aleutian")
