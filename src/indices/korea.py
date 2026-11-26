"""한반도 목표 변수: ERA5 육지 가중 평균 기온·강수 편차, (있으면) ASOS 전국 평균."""
from __future__ import annotations

import pandas as pd
import xarray as xr

from .. import config as C
from ..common import area_mean, series_anom, series_clim


def compute(t2m: xr.DataArray, tp: xr.DataArray) -> pd.DataFrame:
    lf = xr.open_dataarray(C.DATA / "static" / "landfrac_ea.nc")
    lf = lf.assign_coords(lat=t2m.lat.values, lon=t2m.lon.values)
    t = area_mean(t2m, C.REGIONS["korea"], lf).to_series() - 273.15
    p = area_mean(tp, C.REGIONS["korea"], lf).to_series()
    out = pd.DataFrame({"korea_t_raw": t, "korea_p_raw": p,
                        "korea_t": series_anom(t), "korea_p": series_anom(p),
                        "korea_p_clim": series_clim(p)})
    from ..fetch import kma
    try:
        obs = kma.national_daily()
    except Exception:
        obs = None
    if obs is not None and len(obs) > 3650:
        obs = obs.reindex(out.index)
        out["asos_t"] = series_anom(obs["ta"])
        out["asos_p"] = series_anom(obs["rn"])
    return out


def ea_regions(t2m: xr.DataArray, tp: xr.DataArray) -> pd.DataFrame:
    """동아시아 하위 영역(한반도 포함)의 육지 가중 평균 기온·강수 편차 (ERA5)."""
    lf = xr.open_dataarray(C.DATA / "static" / "landfrac_ea.nc")
    lf = lf.assign_coords(lat=t2m.lat.values, lon=t2m.lon.values)
    cols = {}
    for key, (_, reg) in C.EA_SUBREGIONS.items():
        if key == "korea":
            continue
        t = area_mean(t2m, reg, lf).to_series() - 273.15
        p = area_mean(tp, reg, lf).to_series()
        cols[f"{key}_t"] = series_anom(t)
        cols[f"{key}_p"] = series_anom(p)
        cols[f"{key}_p_raw"] = p
        cols[f"{key}_p_clim"] = series_clim(p)
    return pd.DataFrame(cols)
