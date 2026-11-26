"""ECMWF ARCO Zarr(인증 필요)로 Google 원시 자료보다 더 최근 날짜를 채운다.

주의: 이 모듈은 `CDSAPI_KEY`가 없는 환경에서 작성돼 실제 접속으로 검증하지 못했다.
Google ARCO-ERA5 원시 자료가 닿지 않는 최근 며칠만 보충하는 용도로 쓰고,
실패하면 경고만 남기고 넘어간다 (전체 흐름은 Google 경로만으로 완결된다).
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


def extend(after: dt.date, until: dt.date) -> dt.date:
    """after 다음 날부터 until까지 하루씩 채우고, 채운 마지막 날짜를 돌려준다."""
    if not has_key("CDSAPI_KEY") or until <= after:
        return after
    last = after
    try:
        stores = {k: _open(k) for k in STORES}
        d = after + dt.timedelta(days=1)
        while d <= until:
            fetch_day(d, stores)
            last = d
            d += dt.timedelta(days=1)
    except Exception as e:  # 검증되지 않은 경로라 실패해도 전체를 멈추지 않는다
        log.warning("ECMWF ARCO 보충 중단 (%s까지 확보): %s", last, type(e).__name__)
    return last
