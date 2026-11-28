"""WeatherBench2 ERA5 일평균(익명 공개)에서 1979~2022년 자료를 받는다.

- 1.5° 격자(240x121, 13층): 대규모장, 지상 변수, 50 hPa 아래 극관 고도
- 512x256 격자(37층): 10 hPa 60°N 동서풍, 10·30 hPa 극관 고도, 10 hPa 고도장

연도별 파일로 저장하고 이미 있는 파일은 건너뛴다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, get_logger

log = get_logger("fetch.wb2")
WB2_SFC = {"msl": "mean_sea_level_pressure", "t2m": "2m_temperature",
           "tp": "total_precipitation_24hr", "sst": "sea_surface_temperature",
           "ci": "sea_ice_cover", "sd": "snow_depth", "swvl1": "volumetric_soil_water_layer_1",
           "tp_nh": "total_precipitation_24hr"}      # tp_nh: 같은 강수를 북반구 전체로


def _open(url: str) -> xr.Dataset:
    return xr.open_zarr(url, storage_options=dict(token="anon"), chunks=None)


def _years() -> list[int]:
    return list(range(C.START_YEAR, C.WB2_LAST_YEAR + 2))   # 마지막 해는 겹침 검증용(1월 초)


def _tslice(year: int) -> slice:
    end = f"{year}-12-31" if year <= C.WB2_LAST_YEAR else C.WB2_OVERLAP_END
    return slice(f"{year}-01-01", end)


def convert_units(name: str, da: xr.DataArray) -> xr.DataArray:
    """저장 단위: 고도 m, 기압 hPa, 강수 mm/일, 나머지는 ERA5 원래 단위."""
    if name.startswith("z"):
        return da / C.G
    if name == "msl":
        return da / 100.0
    if name in C.PRECIP_FIELDS:
        return da * 1000.0
    return da


def subset(name: str, da: xr.DataArray) -> xr.DataArray:
    if name == "sst":
        return da.sel(lat=slice(C.LAT_SST[0], 90))
    if name == "tp":
        return da.sel(lat=slice(*C.EA_LAT), lon=slice(*C.EA_LON))
    return da.sel(lat=slice(0, 90))       # 2 m 기온도 북반구 전체 (예전에는 동아시아만 받았다)


def _is_current(name: str, out) -> bool:
    """이미 받은 파일이 지금 정의와 같은 영역인지. 예전에 동아시아만 받은 t2m 파일은 다시 받는다."""
    if name != "t2m":
        return True
    from ..common import _NC_LOCK
    with _NC_LOCK, xr.open_dataset(out) as ds:      # HDF5는 스레드에서 동시에 열면 죽는다
        return float(ds.lat.min()) < 1.0


def _field_year(ds: xr.Dataset, name: str, year: int) -> str:
    out = C.DATA / "wb2" / name / f"{year}.nc"
    if out.exists() and _is_current(name, out):
        return "skip"
    if name in C.PL_FIELDS:
        var, lev = C.PL_FIELDS[name]
        da = ds[var].sel(level=lev, drop=True)
    else:
        da = ds[WB2_SFC[name]]
    da = da.sel(time=_tslice(year)).load()
    da = da.transpose("time", "latitude", "longitude").rename(latitude="lat", longitude="lon")
    # 좌표에 1e-14 수준의 부동소수 오차가 있어 반올림한 뒤 자른다 (경계 줄이 빠지지 않게)
    da = da.assign_coords(lat=np.round(da.lat.values, 6), lon=np.round(da.lon.values, 6))
    da = convert_units(name, subset(name, da)).astype("float32").rename(name)
    atomic_to_netcdf(da.to_dataset(), out)
    return "ok"


def _pcap_year(ds: xr.Dataset, year: int) -> str:
    """50 hPa 아래 공통층의 극관(65°N 이북) 평균 고도."""
    out = C.DATA / "wb2" / "pcap" / f"{year}.nc"
    if out.exists():
        return "skip"
    levs = [l for l in C.PCAP_LEVELS if l in ds.level.values]
    z = ds["geopotential"].sel(level=levs, time=_tslice(year)).load()
    z = z.sel(latitude=slice(C.PCAP_LAT, 90))
    w = np.cos(np.deg2rad(z.latitude))
    cap = (z.mean("longitude").weighted(w).mean("latitude") / C.G).astype("float32").rename("pcap")
    atomic_to_netcdf(cap.transpose("time", "level").to_dataset(), out)
    return "ok"


def _strat_year(ds37: xr.Dataset, year: int) -> str:
    """10 hPa 60°N 동서평균 동서풍, 10·30 hPa 극관 고도, 10 hPa 고도장·기온장(1.5°로 내삽)."""
    out = C.DATA / "wb2" / "strat" / f"{year}.nc"
    if out.exists():
        return "skip"
    ts = _tslice(year)
    u = ds37["u_component_of_wind"].sel(level=10, time=ts).load()
    u60 = u.mean("longitude").interp(latitude=60.0).drop_vars(["latitude", "level"])
    z = ds37["geopotential"].sel(level=[10, 30], time=ts).load() / C.G
    zc = z.sel(latitude=slice(C.PCAP_LAT + 0.25, 90))
    cap = zc.mean("longitude").weighted(np.cos(np.deg2rad(zc.latitude))).mean("latitude")
    z10 = z.sel(level=10, drop=True).transpose("time", "latitude", "longitude")
    z10 = z10.interp(latitude=C.LAT_NH, longitude=C.LON, kwargs={"fill_value": None})
    z10 = z10.rename(latitude="lat", longitude="lon")
    t10 = ds37["temperature"].sel(level=10, time=ts, drop=True).load().transpose("time", "latitude", "longitude")
    t10 = t10.interp(latitude=C.LAT_NH, longitude=C.LON, kwargs={"fill_value": None})
    t10 = t10.rename(latitude="lat", longitude="lon")
    ds = xr.Dataset({"u1060": u60.astype("float32"),
                     "pcap": cap.transpose("time", "level").astype("float32"),
                     "z10": z10.astype("float32"), "t10": t10.astype("float32")})
    atomic_to_netcdf(ds, out)
    return "ok"


def run(workers: int = 6) -> None:
    ds = _open(C.WB2_DAILY)
    ds37 = _open(C.WB2_DAILY_37)
    names = list(C.PL_FIELDS) + list(C.SFC_FIELDS)
    jobs = []
    with ThreadPoolExecutor(workers) as ex:
        for y in _years():
            jobs.append(ex.submit(_pcap_year, ds, y))
            jobs.append(ex.submit(_strat_year, ds37, y))
            for n in names:
                jobs.append(ex.submit(_field_year, ds, n, y))
        done = fetched = 0
        for f in as_completed(jobs):
            fetched += f.result() == "ok"
            done += 1
            if done % 100 == 0 or done == len(jobs):
                log.info("WB2 %d/%d (새로 받음 %d)", done, len(jobs), fetched)


if __name__ == "__main__":
    run()
