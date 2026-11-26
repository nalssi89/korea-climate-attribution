"""여러 단계에서 같이 쓰는 도구: 로그, 격자 변환, 평년값, 영역 평균, 그림 설정."""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from . import config as C


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                            format="%(asctime)s %(name)s | %(message)s", datefmt="%H:%M:%S")
    return log


def has_key(name: str) -> bool:
    """환경변수 존재 여부만 본다. 값은 어디에도 출력하지 않는다."""
    return bool(os.environ.get(name))


_NC_LOCK = threading.Lock()


def atomic_to_netcdf(ds: xr.Dataset, path: Path) -> None:
    """.part 임시 파일에 쓰고 끝나면 이름을 바꾼다 (중단돼도 반쪽 파일이 남지 않게)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with _NC_LOCK:      # HDF5 라이브러리는 스레드에서 동시에 쓰면 죽는다
        ds.to_netcdf(tmp)
    tmp.rename(path)


# ------------------------------------------------------------------ 격자 변환
def box_weights_lat(lat_src: np.ndarray, lat_tgt: np.ndarray, half: float = 0.75) -> np.ndarray:
    """0.25° 위도 → 1.5° 위도 상자 평균 가중치 (cos 위도 가중, 상자 끝 점은 절반)."""
    w = np.zeros((lat_tgt.size, lat_src.size))
    for i, lt in enumerate(lat_tgt):
        d = np.abs(lat_src - lt)
        k = np.where(d <= half + 1e-6, 1.0, 0.0)
        k[np.abs(d - half) < 1e-6] = 0.5
        k = k * np.cos(np.deg2rad(np.clip(lat_src, -89.875, 89.875)))
        w[i] = k / k.sum()
    return w


def box_weights_lon(lon_src: np.ndarray, lon_tgt: np.ndarray, half: float = 0.75) -> np.ndarray:
    w = np.zeros((lon_tgt.size, lon_src.size))
    for i, ln in enumerate(lon_tgt):
        d = np.abs((lon_src - ln + 180.0) % 360.0 - 180.0)
        k = np.where(d <= half + 1e-6, 1.0, 0.0)
        k[np.abs(d - half) < 1e-6] = 0.5
        w[i] = k / k.sum()
    return w


def box_regrid(a: np.ndarray, wlat: np.ndarray, wlon: np.ndarray) -> np.ndarray:
    """(…, 위도, 경도) 배열을 상자 평균한다. NaN은 빼고 평균한다 (해수면온도, 해빙)."""
    a = np.asarray(a, dtype="float64")
    bad = np.isnan(a)
    if bad.any():
        num = wlat @ np.where(bad, 0.0, a) @ wlon.T
        den = wlat @ (~bad).astype("float64") @ wlon.T
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 1e-6, num / den, np.nan).astype("float32")
    return (wlat @ a @ wlon.T).astype("float32")


# ------------------------------------------------------------------ 영역 평균
def lon_mask(lon: np.ndarray, west: float, east: float) -> np.ndarray:
    west, east = west % 360, east % 360
    return (lon >= west) & (lon <= east) if west <= east else (lon >= west) | (lon <= east)


def area_mean(da: xr.DataArray, region, weights: xr.DataArray | None = None) -> xr.DataArray:
    """cos 위도 가중 영역 평균. region = (남, 북, 서, 동). NaN 격자는 뺀다."""
    s, n, w, e = region
    sub = da.sel(lat=slice(s, n)).isel(lon=lon_mask(da.lon.values, w, e))
    wgt = np.cos(np.deg2rad(sub.lat)) * xr.ones_like(sub.lon)
    if weights is not None:
        wgt = wgt * weights.sel(lat=sub.lat, lon=sub.lon)
    return sub.weighted(wgt.fillna(0)).mean(("lat", "lon"))


# ------------------------------------------------------------------ 평년값과 편차
def _harmonic_smooth(clim: np.ndarray, nharm: int = 4) -> np.ndarray:
    """일별 평년값(366일)을 연주기의 앞쪽 조화성분만 남겨 매끄럽게 한다."""
    f = np.fft.rfft(clim, axis=0)
    f[nharm + 1:] = 0
    return np.fft.irfft(f, n=clim.shape[0], axis=0)


def daily_clim(da: xr.DataArray, years=C.CLIM, nharm: int = 4) -> xr.DataArray:
    """평년 기간의 일별 평년값 (dayofyear 1~366, 조화 평활)."""
    sub = da.sel(time=slice(f"{years[0]}-01-01", f"{years[1]}-12-31"))
    doy = _doy366(sub.time)
    g = sub.groupby(xr.DataArray(doy, dims="time", name="doy")).mean("time")
    g = g.reindex(doy=np.arange(1, 367)).interpolate_na("doy", fill_value="extrapolate") \
        if g.doy.size < 366 else g
    sm = _harmonic_smooth(g.values.astype("float64"), nharm)
    return g.copy(data=sm.astype("float32"))


def _doy366(time) -> np.ndarray:
    """윤년 여부와 무관하게 같은 달·일이 같은 번호가 되는 날짜 번호 (2월 29일 = 60)."""
    t = pd.DatetimeIndex(np.asarray(time))
    table = pd.date_range("2000-01-01", "2000-12-31")
    lut = np.zeros((13, 32), dtype=int)
    lut[table.month, table.day] = table.dayofyear
    return lut[t.month, t.day]


def anomaly(da: xr.DataArray, clim: xr.DataArray) -> xr.DataArray:
    doy = xr.DataArray(_doy366(da.time), dims="time")
    return (da - clim.sel(doy=doy)).drop_vars("doy")


def standardize(s: pd.Series, years=C.CLIM) -> pd.Series:
    base = s[f"{years[0]}":f"{years[1]}"]
    return (s - base.mean()) / base.std()


def detrend_by_month(s: pd.Series, end_year: int | None = None) -> pd.Series:
    """달마다 따로 구한 선형 추세(연도에 대한)를 일별 편차에서 뺀다."""
    out = s.copy()
    for m in range(1, 13):
        sel = s.index.month == m
        mon = s[sel].groupby(s.index[sel].year).mean().dropna()
        if end_year:
            mon = mon[mon.index <= end_year]
        b, a = np.polyfit(mon.index.values, mon.values, 1)
        out[sel] = s[sel] - (a + b * s.index[sel].year)
    return out


# ------------------------------------------------------------------ 자료 읽기
def open_field(name: str) -> xr.DataArray:
    """1979년부터 최근까지 이어 붙인 일별 1.5° 장 (fetch.merge가 만든 파일)."""
    return xr.open_dataarray(C.DATA / "merged" / f"{name}.nc")


def ea_crop(da: xr.DataArray) -> xr.DataArray:
    """동아시아 분석 영역(C.EA_LAT, C.EA_LON)만 자른다. 북반구로 저장한 2 m 기온을 예전 동아시아 지수와 같게 쓰려고 둔다."""
    return da.sel(lat=slice(*C.EA_LAT), lon=slice(*C.EA_LON))


def load_indices() -> pd.DataFrame:
    return pd.read_csv(C.OUT / "indices_daily.csv", index_col=0, parse_dates=True)


# ------------------------------------------------------------------ 그림
def setup_plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        import koreanize_matplotlib  # noqa: F401  (나눔고딕 등록)
    except ImportError:
        get_logger("plot").warning("koreanize-matplotlib가 없어 한글이 깨질 수 있다")
    plt.rcParams.update({"axes.unicode_minus": False, "figure.dpi": 110, "savefig.dpi": 130,
                         "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
                         "axes.spines.right": False})
    return plt


def savefig(fig, name: str) -> Path:
    import matplotlib.pyplot as plt
    p = C.REPORTS / "figures" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ 시계열 평년값, 장 평년값 캐시
def series_clim(s: pd.Series, years=C.CLIM, nharm: int = 4) -> pd.Series:
    """일별 시계열의 평년값을 같은 날짜 색인으로 돌려준다."""
    base = s[f"{years[0]}":f"{years[1]}"]
    g = base.groupby(_doy366(base.index)).mean().reindex(np.arange(1, 367)).interpolate(limit_direction="both")
    sm = _harmonic_smooth(g.values.astype("float64"), nharm)
    return pd.Series(sm[_doy366(s.index) - 1], index=s.index)


def series_anom(s: pd.Series, **kw) -> pd.Series:
    return s - series_clim(s, **kw)


def field_clim(name: str) -> xr.DataArray:
    """장의 일별 평년값(1991~2020). 한 번 계산하면 data/clim에 저장해 다시 쓴다."""
    p = C.DATA / "clim" / f"{name}.nc"
    if p.exists():
        cl = xr.open_dataarray(p).load()
        with open_field(name) as f:     # 예전 영역(동아시아만 받던 t2m)으로 만든 평년값이면 다시 만든다
            same = cl.lat.size == f.lat.size and cl.lon.size == f.lon.size
        if same:
            return cl
    da = open_field(name).sel(time=slice(f"{C.CLIM[0]}-01-01", f"{C.CLIM[1]}-12-31")).load()
    cl = daily_clim(da).rename(name)
    atomic_to_netcdf(cl.to_dataset(), p)
    return cl


def window_anom(name: str, start, end) -> xr.DataArray:
    """기간 평균 편차장."""
    da = open_field(name).sel(time=slice(str(start), str(end))).load()
    return anomaly(da, field_clim(name)).mean("time")


# ------------------------------------------------------------------ 색, 기간 도구
INK, INK2, GRIDC = "#191919", "#666666", "#e7e7e7"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647")
WARM, COOL = "#dc3c3d", "#257de0"       # 양(+)/음(-) 편차


def diverging_cmap():
    """파랑-회색-빨강 발산 색상표 (가운데는 무채색)."""
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list(
        "bgr", ["#0e3d7e", "#2370cd", "#84b9f3", "#cce3fd", "#efefef", "#f8cfc4", "#ee8a70", "#dc3c3d", "#8c1c1d"], N=256)


def shifted_window(start: pd.Timestamp, end: pd.Timestamp, year_shift: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """같은 달·일의 다른 해 기간 (끝 날짜를 옮기고 길이를 유지한다)."""
    e = end - pd.DateOffset(years=-year_shift) if year_shift else end
    return e - (end - start), e


def same_season_windows(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """해마다 같은 기간의 평균값 (색인은 끝 날짜의 연도). 순위·백분위 계산에 쓴다."""
    out = {}
    for y in range(s.index[0].year, end.year + 1):
        a, b = shifted_window(start, end, y - end.year)
        seg = s[a:b]
        if a >= s.index[0] and len(seg) == (end - start).days + 1 and seg.notna().all():
            out[b.year] = seg.mean()
    return pd.Series(out)
