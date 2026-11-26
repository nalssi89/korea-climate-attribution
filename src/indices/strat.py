"""성층권: 10 hPa 60°N 동서평균풍, SSW 발생일 탐지, 극관 고도 표준화 편차."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import _doy366, _harmonic_smooth, series_anom


def detect_ssw(u: pd.Series) -> pd.DataFrame:
    """Charlton & Polvani (2007) 기준의 주요 SSW 중심일.

    - 11~3월에 10 hPa 60°N 동서평균풍이 동풍(<0)으로 바뀐 첫 날
    - 앞 사건 뒤 서풍이 20일 연속 돌아온 다음이라야 새 사건
    - 4월 말 전에 서풍이 10일 연속 돌아오지 않으면 최종승온으로 보고 뺀다
    """
    u = u.dropna()
    rows = []
    for y in range(u.index[0].year, u.index[-1].year + 1):
        win = u[f"{y}-11-01":f"{y + 1}-03-31"]
        if win.empty or win.index[0] > pd.Timestamp(y, 11, 1):
            continue
        tail = u[f"{y}-11-01":f"{y + 1}-04-30"]
        west_run = C.SSW_SEP_DAYS          # 겨울 첫 사건은 바로 인정
        in_event = False
        for t, val in win.items():
            if val < 0:
                if not in_event and west_run >= C.SSW_SEP_DAYS:
                    after = tail[t:].iloc[1:]
                    ret = (after > 0).astype(int)
                    run = ret.groupby((ret == 0).cumsum()).cumsum()
                    returned = bool((run >= C.SSW_RETURN_DAYS).any())
                    complete = tail.index[-1] >= pd.Timestamp(y + 1, 4, 30)
                    if returned or not complete:
                        east = after[: (after > 0).idxmax()] if (after > 0).any() else after
                        rows.append(dict(date=t.date(), winter=f"{y}/{str(y + 1)[2:]}",
                                         min_u=round(float(min(val, east.min() if len(east) else val)), 1),
                                         confirmed=returned))
                    in_event = True
                west_run = 0
            else:
                west_run += 1
                if west_run >= C.SSW_SEP_DAYS:
                    in_event = False
    return pd.DataFrame(rows)


def pch_std_anom(pcap: xr.DataArray) -> xr.DataArray:
    """극관 고도의 층별 표준화 편차 (평년 기간의 날짜별 평균·표준편차 기준, 조화 평활)."""
    base = pcap.sel(time=slice(f"{C.CLIM[0]}-01-01", f"{C.CLIM[1]}-12-31"))
    doy_b = xr.DataArray(_doy366(base.time), dims="time", name="doy")
    mean = base.groupby(doy_b).mean("time")
    sm_mean = mean.copy(data=_harmonic_smooth(mean.values.astype("float64")))
    doy = xr.DataArray(_doy366(pcap.time), dims="time")
    anom = (pcap - sm_mean.sel(doy=doy)).drop_vars("doy")
    var = (anom.sel(time=base.time) ** 2).groupby(doy_b).mean("time")
    sm_sd = np.sqrt(var.copy(data=np.maximum(_harmonic_smooth(var.values.astype("float64")), 1e-6)))
    return (anom / sm_sd.sel(doy=doy)).drop_vars("doy").rename("pch")


def compute(strat: xr.Dataset) -> tuple[pd.DataFrame, pd.DataFrame, xr.DataArray]:
    u = strat.u1060.to_series()
    pch = pch_std_anom(strat.pcap)
    df = pd.DataFrame({"u1060": u, "pv": series_anom(u),
                       "pch10": pch.sel(level=10).to_series(), "pch100": pch.sel(level=100).to_series(),
                       "pch500": pch.sel(level=500).to_series()})
    return df, detect_ssw(u), pch
