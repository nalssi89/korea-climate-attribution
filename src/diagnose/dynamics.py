"""역학 진단: Takaya-Nakamura 파동활동 플럭스, 850 hPa 온도 이류, 수증기 수송."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import _doy366, field_clim, open_field, shifted_window, window_anom

A_EARTH, OMEGA = 6.371e6, 7.292e-5


def _ddx(f: np.ndarray, lon_rad: np.ndarray) -> np.ndarray:
    """경도 미분 (전구 주기 경계)."""
    d = lon_rad[1] - lon_rad[0]
    return (np.roll(f, -1, -1) - np.roll(f, 1, -1)) / (2 * d)


def tn_flux(start, end, level: int = 250) -> xr.Dataset:
    """정상 로스비파의 수평 파동활동 플럭스 (Takaya & Nakamura 2001, 식 38의 수평 성분).

    섭동은 기간 평균 고도 편차(준지균 유선함수 ψ' = g z'/f), 기본장은 같은 날짜들의 평년 바람.
    """
    za = window_anom(f"z{level}", start, end)
    doys = _doy366(pd.date_range(start, end))
    U = field_clim(f"u{level}").sel(doy=doys).mean("doy")
    V = field_clim(f"v{level}").sel(doy=doys).mean("doy")
    lat, lon = np.deg2rad(za.lat.values), np.deg2rad(za.lon.values)
    cos = np.cos(lat)[:, None]
    f = 2 * OMEGA * np.sin(lat)[:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        psi = C.G * za.values / f
        px = _ddx(psi, lon)
        py = np.gradient(psi, lat, axis=0)
        pxx = _ddx(px, lon)
        pyy = np.gradient(py, lat, axis=0)
        pxy = np.gradient(px, lat, axis=0)
        u, v = U.values, V.values
        coef = (level / 1000.0) * cos / (2 * np.hypot(u, v))
        t1, t2, t3 = px ** 2 - psi * pxx, px * py - psi * pxy, py ** 2 - psi * pyy
        fx = coef * (u / (A_EARTH ** 2 * cos ** 2) * t1 + v / (A_EARTH ** 2 * cos) * t2)
        fy = coef * (u / (A_EARTH ** 2 * cos) * t2 + v / A_EARTH ** 2 * t3)
    bad = (np.abs(za.lat.values)[:, None] < 20) | (za.lat.values[:, None] > 85) | (u < 1.0)   # 저위도·극·동풍 영역 제외
    fx[bad], fy[bad] = np.nan, np.nan
    return xr.Dataset({"fx": (("lat", "lon"), fx), "fy": (("lat", "lon"), fy), "za": za,
                       "u": U.drop_vars("doy", errors="ignore")}, coords=dict(lat=za.lat, lon=za.lon))


def _advection(u: xr.DataArray, v: xr.DataArray, t: xr.DataArray) -> xr.DataArray:
    """수평 온도 이류 -V·∇T (K/일)."""
    lat, lon = np.deg2rad(t.lat.values), np.deg2rad(t.lon.values)
    cos = np.cos(lat)[:, None]
    tx = np.gradient(t.values, lon, axis=-1) / (A_EARTH * cos)
    ty = np.gradient(t.values, lat, axis=-2) / A_EARTH
    return t.copy(data=-(u.values * tx + v.values * ty) * 86400.0)


def _box(name: str, a, b, region) -> xr.DataArray:
    s, n, w, e = region
    return open_field(name).sel(time=slice(str(a.date()), str(b.date())), lat=slice(s, n), lon=slice(w, e)).load()


def low_level(start, end, region=(10, 65, 80, 170)) -> xr.Dataset:
    """850 hPa 온도 이류와 수증기 수송(q·V)의 기간 평균과 편차.

    곱으로 된 양이라 평년값도 평년 기간(1991~2020) 각 해 같은 날짜의 일별 값을 계산해 평균한다.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    def calc(a, b):
        u, v, t, q = (_box(n, a, b, region) for n in ("u850", "v850", "t850", "q850"))
        return xr.Dataset({"adv": _advection(u, v, t).mean("time"), "qu": (q * u).mean("time") * 1000,
                           "qv": (q * v).mean("time") * 1000, "u": u.mean("time"), "v": v.mean("time"),
                           "q": q.mean("time") * 1000})
    now = calc(start, end)
    clim = [calc(*shifted_window(start, end, y - end.year)) for y in range(C.CLIM[0], C.CLIM[1] + 1)]
    clim = xr.concat(clim, "year").mean("year")
    out = now - clim
    out = out.rename({k: f"{k}_anom" for k in out.data_vars})
    return xr.merge([out, now])
