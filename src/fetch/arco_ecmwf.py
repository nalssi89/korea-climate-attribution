"""ECMWF ARCO Zarr(인증 필요): Google 원시 자료보다 더 최근 날짜 보충과 겹치는 날의 교차 검증.

2026-11-26 실제 접속으로 확인한 사실
- 기압면 저장소(timeChunked)는 13개 층(1000~50 hPa)뿐이라 10·30 hPa가 없다. 그래서 성층권 항목까지 갖춘
  하루 파일을 이 경로만으로는 만들 수 없다. 보충은 10·30 hPa가 저장소에 생길 때만 시도한다.
- 기압면 끝 시각이 Google ARCO-ERA5 원시 자료보다 하루쯤 이르다 (확인 시점 2026-11-19 18 UTC).
- 지상 저장소에는 해빙(siconc)이 없다.
그래서 이 경로는 주로 Google 경로로 만든 최근 하루 파일을 독립 자료와 비교하는 데 쓴다.
"""
from __future__ import annotations

import datetime as dt
import os

import numpy as np
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, get_logger, has_key
from . import arco_raw as A

log = get_logger("fetch.ecmwf")
STORES = {
    "PL": f"{C.ECMWF_ARCO}/cadl-arco-time-048/arco/reanalysis_era5_pressure_levels/pl/timeChunked.zarr",
    "SL": f"{C.ECMWF_ARCO}/cadl-arco-time-002/arco/reanalysis_era5_single_levels/sfc/timeChunked.zarr",
}
SHORT = {"geopotential": "z", "u_component_of_wind": "u", "v_component_of_wind": "v",
         "temperature": "t", "specific_humidity": "q", "mean_sea_level_pressure": "msl",
         "2m_temperature": "t2m", "total_precipitation": "tp",
         "sea_surface_temperature": "sst", "sea_ice_cover": "siconc"}


def _open(kind: str) -> xr.Dataset:
    from obstore.store import HTTPStore
    from zarr.storage import ObjectStore
    http = HTTPStore(STORES[kind], client_options={
        "default_headers": {"Authorization": f"Bearer {os.environ['CDSAPI_KEY']}"}, "timeout": "300s"})
    ds = xr.open_zarr(ObjectStore(http, read_only=True), consolidated=True, chunks=None)   # 반드시 chunks=None
    ren = {a: b for a, b in (("valid_time", "time"), ("pressureLevel", "level"), ("pressure_level", "level"),
                             ("isobaricInhPa", "level"), ("lat", "latitude"), ("lon", "longitude"))
           if a in ds.variables or a in ds.dims}
    return ds.rename(ren)


def _var(ds: xr.Dataset, long_name: str) -> xr.DataArray:
    for n in (long_name, SHORT[long_name], "ci" if long_name == "sea_ice_cover" else None):
        if n and n in ds:
            return ds[n]
    raise KeyError(long_name)


def fetch_day(date: dt.date, stores: dict) -> None:
    out = A.day_path(date)
    if out.exists():
        return
    arrs = {}
    for it in A.items():
        kind, var, fname = it.path.split("/")
        da = _var(stores[kind], var)
        times = [np.datetime64(f"{date}T{h:02d}:00") for h in it.hours]
        da = da.sel(time=times)
        if kind == "PL":
            da = da.sel(level=int(fname.split(".")[0]))
        da = da.load().transpose("time", "latitude", "longitude")
        da = da.assign_coords(longitude=da.longitude % 360).sortby("longitude").sortby("latitude", ascending=False)
        assert da.shape[1:] == (A.NLAT, A.NLON)
        arrs[it.key] = da.values[:, it.rows[0]:it.rows[1] + 1, it.cols[0]:it.cols[1] + 1]
    ds = A.reduce_day(arrs, A.items()).expand_dims(time=[np.datetime64(date, "ns")])
    ds.attrs["source"] = "ECMWF ARCO"
    atomic_to_netcdf(ds, out)


def coverage() -> dict:
    """저장소의 끝 시각과 층 목록 (상태 보고용)."""
    st = {k: _open(k) for k in STORES}
    pl = st["PL"]
    return dict(pl_end=str(pl.time.values[-1])[:16], sl_end=str(st["SL"].time.values[-1])[:16],
                levels=[int(v) for v in pl.level.values], has_siconc=bool({"siconc", "ci"} & set(st["SL"].data_vars)))


def cross_check(date: dt.date) -> dict:
    """Google 경로로 만든 하루 파일과 ECMWF ARCO 같은 날 값(1.5° 상자 평균)을 비교한다."""
    from ..common import box_regrid, box_weights_lat, box_weights_lon
    st = {k: _open(k) for k in STORES}
    mine = xr.open_dataset(A.day_path(date))
    rows = {}
    for key, kind, var, lev, scale in (("z500", "PL", "z", 500, 1 / C.G), ("t850", "PL", "t", 850, 1.0),
                                       ("u250", "PL", "u", 250, 1.0), ("msl", "SL", "msl", None, 0.01)):
        da = st[kind][var].sel(time=[np.datetime64(f"{date}T{h:02d}:00") for h in A.H6])
        if lev:
            da = da.sel(level=lev)
        da = da.load().assign_coords(longitude=lambda d: d.longitude % 360).sortby("longitude").sortby("latitude", ascending=False)
        a = da.values.mean(0)[: A._rows(0, 90)[1] + 1] * scale
        r = box_regrid(a, box_weights_lat(A.LAT_SRC[: a.shape[0]], C.LAT_NH), box_weights_lon(A.LON_SRC, C.LON))
        b = mine[key].values[0]
        d = r - b
        rows[key] = dict(bias=round(float(d.mean()), 4), rmse=round(float(np.sqrt((d ** 2).mean())), 4),
                         corr=round(float(np.corrcoef(r.ravel(), b.ravel())[0, 1]), 6))
    return dict(date=str(date), fields=rows)


def extend(after: dt.date, until: dt.date) -> dt.date:
    """after 다음 날부터 until까지 하루씩 채우고, 채운 마지막 날짜를 돌려준다."""
    if not has_key("CDSAPI_KEY") or until <= after:
        return after
    last = after
    try:
        stores = {k: _open(k) for k in STORES}
        need = {int(it.path.split("/")[2].split(".")[0]) for it in A.items() if it.path.startswith("PL")}
        missing = sorted(need - {int(v) for v in stores["PL"].level.values})
        if missing:
            log.info("ECMWF ARCO 기압면에 %s hPa가 없어 하루 파일 보충을 건너뛴다", missing)
            return after
        d = after + dt.timedelta(days=1)
        while d <= until:
            fetch_day(d, stores)
            last = d
            d += dt.timedelta(days=1)
    except Exception as e:  # 검증되지 않은 경로라 실패해도 전체를 멈추지 않는다
        log.warning("ECMWF ARCO 보충 중단 (%s까지 확보): %s", last, type(e).__name__)
    return last
