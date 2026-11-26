"""성층권: 10 hPa 60°N 동서평균풍, SSW 발생일 탐지, 극관 고도 표준화 편차."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import _doy366, _harmonic_smooth, series_anom, series_clim


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


# ------------------------------------------------------------------ 2026년 11월 사례 판정에 쓰는 성층권 일별 진단
def _coslat_mean(da: xr.DataArray, lat0: float, lat1: float) -> pd.Series:
    sub = da.sel(lat=slice(lat0, lat1))
    w = np.cos(np.deg2rad(sub.lat.clip(max=89.99)))
    return sub.mean("lon").weighted(w).mean("lat").to_series()


def polar_cap_t10(t10: xr.DataArray) -> pd.DataFrame:
    """극관(60~90°N) 10 hPa 기온과 극-60°N 동서평균 기온 차(양이면 남북 기온 경도 역전)."""
    zm = t10.mean("lon")
    return pd.DataFrame({"t10_cap": _coslat_mean(t10, 60, 90),
                         "t10_grad": (zm.sel(lat=slice(85, 90)).mean("lat") - zm.sel(lat=60.0)).to_series()})


def eddy_heat_flux(v: xr.DataArray, t: xr.DataArray, lat=C.HEATFLUX_LAT) -> pd.Series:
    """100 hPa 에디 열속 [v*T*] (K m/s), 45~75°N cos 가중 평균. 일평균 장에서 구한다."""
    v = v.sel(lat=slice(*lat))
    t = t.sel(lat=slice(*lat))
    flux = ((v - v.mean("lon")) * (t - t.mean("lon"))).mean("lon")
    w = np.cos(np.deg2rad(flux.lat))
    return flux.weighted(w).mean("lat").to_series().rename("vt100")


def wave_amplitude(z10: xr.DataArray, lat: float = 60.0) -> pd.DataFrame:
    """10 hPa 고도의 60°N 파수 1·2 진폭 (m)."""
    a = z10.sel(lat=lat).values
    f = np.fft.rfft(a, axis=-1) * 2 / a.shape[-1]
    t = pd.DatetimeIndex(z10.time.values)
    return pd.DataFrame({"wave1": np.abs(f[:, 1]), "wave2": np.abs(f[:, 2])}, index=t)


def vortex_geometry(z10: xr.DataArray, lat_min: float = 30.0, min_frac: float = 0.15) -> pd.DataFrame:
    """10 hPa 극소용돌이 모양: 가장자리 안쪽 면적, 중심 위도·경도, 조각 수.

    가장자리는 그날의 평년 60°N 동서평균 고도로 둔다(날짜별 평년, 조화 평활). 그보다 고도가 낮은 영역을
    소용돌이로 보고, 경도 방향은 이어 붙이고 극점 줄은 하나로 묶어 연결 성분을 센다.
    전체 소용돌이 면적의 15% 이상인 성분만 조각으로 친다 (2개 이상이면 분리형 후보).
    """
    from scipy import ndimage
    sub = z10.sel(lat=slice(lat_min, 90))
    edge_clim = series_clim(z10.sel(lat=60.0).mean("lon").to_series())   # 날짜별 평년값
    lat = sub.lat.values
    lon = np.deg2rad(sub.lon.values)
    area = np.cos(np.deg2rad(np.clip(lat, None, 89.25)))[:, None] * np.ones(lon.size)
    x = np.cos(np.deg2rad(lat))[:, None] * np.cos(lon)
    y = np.cos(np.deg2rad(lat))[:, None] * np.sin(lon)
    zc = np.sin(np.deg2rad(lat))[:, None] * np.ones(lon.size)
    vals = sub.values
    rows = []
    for i in range(vals.shape[0]):
        inside = vals[i] < edge_clim.iloc[i]
        lab, n = ndimage.label(inside)
        if n:
            # 경도 0°와 마지막 칸을 잇고, 극점 근처 줄의 성분은 모두 같은 것으로 본다
            parent = np.arange(n + 1)

            def find(a):
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a
            pairs = [(a, b) for a, b in zip(lab[:, 0], lab[:, -1]) if a and b]
            top = [a for a in np.unique(lab[-2:]) if a]
            pairs += [(top[0], t) for t in top[1:]]
            for a, b in pairs:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
            lab = np.vectorize(find)(lab) * (lab > 0)
        ids = [k for k in np.unique(lab) if k]
        tot = float(area[inside].sum())
        sizes = sorted((float(area[lab == k].sum()) for k in ids), reverse=True)
        big = [s for s in sizes if tot > 0 and s >= min_frac * tot]
        if tot > 0:
            w = area * inside
            cx, cy, cz = (float((q * w).sum() / w.sum()) for q in (x, y, zc))
            clat = float(np.degrees(np.arctan2(cz, np.hypot(cx, cy))))
            clon = float(np.degrees(np.arctan2(cy, cx)) % 360)
        else:
            clat = clon = np.nan
        frac2 = sizes[1] / tot if len(sizes) > 1 and tot > 0 else 0.0
        rows.append((tot, clat, clon, len(big), frac2))
    df = pd.DataFrame(rows, columns=["vortex_area", "vortex_lat", "vortex_lon", "vortex_pieces", "vortex_frac2"],
                      index=pd.DatetimeIndex(sub.time.values))
    cell = (6.371e3 ** 2) * np.deg2rad(1.5) ** 2 / 1e6        # 적도 1.5° 칸 면적 (10^6 km²)
    df["vortex_area"] = df["vortex_area"] * cell
    return df
