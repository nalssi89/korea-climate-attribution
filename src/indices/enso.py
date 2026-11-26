"""엔소: Niño3.4 해수면온도 편차(일별), 월평균과 3개월 이동평균(ONI 방식)."""
from __future__ import annotations

import pandas as pd
import xarray as xr

from .. import config as C
from ..common import area_mean, series_anom


def compute(sst: xr.DataArray) -> tuple[pd.Series, pd.DataFrame]:
    n34 = series_anom(area_mean(sst, C.REGIONS["nino34"]).to_series()).rename("nino34")
    mon = n34.resample("MS").agg(["mean", "count"])
    mon = mon["mean"].where(mon["count"] >= 20)          # 20일 미만인 달은 쓰지 않는다
    oni = mon.rolling(3, center=True, min_periods=3).mean()
    table = pd.DataFrame({"nino34_monthly": mon.round(3), "oni": oni.round(3)})
    table.index.name = "month"
    noaa = C.DATA / "noaa" / "oni.csv"
    if noaa.exists():
        table = table.join(pd.read_csv(noaa, parse_dates=["month"]).set_index("month"))
    return n34, table


def winter_phase(oni: pd.Series) -> pd.DataFrame:
    """겨울(DJF 평균, 1월에 붙은 ONI)별 엔소 위상."""
    jan = oni[oni.index.month == 1].dropna()
    ph = jan.apply(lambda v: "엘니뇨" if v >= C.ONI_THRESHOLD else ("라니냐" if v <= -C.ONI_THRESHOLD else "중립"))
    return pd.DataFrame({"winter": [f"{t.year - 1}/{str(t.year)[2:]}" for t in jan.index],
                         "oni_djf": jan.values, "phase": ph.values}, index=jan.index.year)
