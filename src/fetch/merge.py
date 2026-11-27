"""WeatherBench2(1979~2022)와 ARCO-ERA5(2023~)를 같은 1.5° 격자에서 이어 붙이고, 겹침 구간으로 검증한다."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, get_logger
from . import arco_raw as A

log = get_logger("fetch.merge")
DIMS = {"sst": ("lat_sst", "lon"), "tp": ("lat_ea", "lon_ea")}
MAY_HAVE_NAN = ("sst", "ci", "sd", "swvl1")      # 바다·육지에만 정의된 장


def _round(ds):
    """좌표의 부동소수 오차를 없앤다."""
    return ds.assign_coords({k: np.round(ds[k].values, 6) for k in ("lat", "lon") if k in ds.coords})


def _wb2(kind: str, last_year: int) -> xr.Dataset:
    files = [C.DATA / "wb2" / kind / f"{y}.nc" for y in range(C.START_YEAR, last_year + 1)]
    return _round(xr.concat([xr.open_dataset(f).load() for f in files], "time"))


def _arco(days: list[dt.date]) -> xr.Dataset:
    return xr.concat([xr.open_dataset(A.day_path(d)).load() for d in days], "time")


def _up_to_date(path, end: dt.date) -> bool:
    if not path.exists():
        return False
    with xr.open_dataset(path) as ds:
        if path.stem == "t2m" and float(ds.lat.min()) > 1.0:     # 예전에 동아시아만 병합한 파일
            return False
        return pd.Timestamp(ds.time.values[-1]).date() == end and \
            pd.Timestamp(ds.time.values[0]).year == C.START_YEAR


def _wb2_strat(last_year: int) -> xr.Dataset:
    """WB2 쪽 성층권·극관 자료를 ARCO 쪽과 같은 모양으로 맞춘다."""
    s = _wb2("strat", last_year)
    low = _wb2("pcap", last_year).pcap
    pcap = xr.concat([s.pcap, low], "level").sel(level=C.PCAP_LEVELS)
    out = xr.Dataset({"u1060": s.u1060, "pcap": pcap.transpose("time", "level")})
    for n in C.STRAT_FIELDS:
        out[n] = _fill_pole(s[n])
    return out


def _fill_pole(da: xr.DataArray) -> xr.DataArray:
    """512x256 격자는 극점이 없어 90°N 줄이 빈다. 극점 값은 88.5°N 동서평균으로 채운다."""
    return da.where(da.lat < 90, da.sel(lat=88.5).mean("lon"))


def _arco_only_up_to_date(path, end: dt.date) -> bool:
    if not path.exists():
        return False
    with xr.open_dataset(path) as ds:
        t = pd.DatetimeIndex(ds.time.values)
    return t[-1].date() == end and str(t[0].date()) == C.ARCO_FIRST


def build_arco_only(name: str, arco: xr.Dataset, days: list[dt.date]) -> None:
    """WB2에 없는 장(C.ARCO_ONLY_FIELDS)은 ARCO 기간(2023~)만 병합한다. 평년값은 그 장에 맞는 다른 방법으로 만든다."""
    da = _round(arco[name]).sel(lat=C.LAT_NH, lon=C.LON).astype("float32").rename(name)
    assert da.time.to_index().is_unique and da.time.size == len(days), f"{name}: 날짜가 빠졌거나 겹친다"
    atomic_to_netcdf(da.to_dataset(), C.DATA / "merged" / f"{name}.nc")
    log.info("병합(ARCO 기간만) %s %s", name, dict(da.sizes))


def build(end: dt.date) -> None:
    out = C.DATA / "merged"
    start = dt.date.fromisoformat(C.ARCO_FIRST)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    targets = C.ALL_FIELDS + ["strat"]
    main_ok = all(_up_to_date(out / f"{n}.nc", end) for n in targets)
    extra = [n for n in C.ARCO_ONLY_FIELDS if not _arco_only_up_to_date(out / f"{n}.nc", end)]
    if main_ok and not extra:
        log.info("병합 파일이 이미 %s까지 있다", end)
        return
    log.info("ARCO 일파일 %d개 읽는 중", len(days))
    arco = _arco(days)
    for name in extra:
        build_arco_only(name, arco, days)
    if main_ok:
        return
    strat_w = _wb2_strat(C.WB2_LAST_YEAR)
    for name in C.ALL_FIELDS:
        w = strat_w[name] if name in C.STRAT_FIELDS else _wb2(name, C.WB2_LAST_YEAR)[name]
        a = arco[name].rename(dict(zip(DIMS.get(name, ("lat", "lon")), ("lat", "lon"))))
        a = _round(a).sel(lat=w.lat, lon=w.lon)
        da = xr.concat([w, a], "time").astype("float32").rename(name)
        assert da.time.to_index().is_unique and len(da.time) == (end - dt.date(C.START_YEAR, 1, 1)).days + 1, \
            f"{name}: 날짜가 빠졌거나 겹친다"
        if name not in MAY_HAVE_NAN:
            assert not bool(da.isnull().any()), f"{name}: 결측이 있다"
        atomic_to_netcdf(da.to_dataset(), out / f"{name}.nc")
        log.info("병합 %s %s", name, dict(da.sizes))
    st = xr.concat([strat_w[["u1060", "pcap"]], arco[["u1060", "pcap"]]], "time")
    atomic_to_netcdf(st.astype("float32"), out / "strat.nc")
    validate(arco)


def validate(arco: xr.Dataset) -> pd.DataFrame:
    """2023-01-01~09 겹침 구간에서 두 자료의 차이를 표로 남긴다 (자료 이음매 점검)."""
    y = C.WB2_LAST_YEAR + 1
    sl = slice(C.ARCO_FIRST, C.WB2_OVERLAP_END)
    a_all = arco.sel(time=sl)
    rows = []
    wst = xr.open_dataset(C.DATA / "wb2" / "strat" / f"{y}.nc")
    for name in C.ALL_FIELDS:
        w = _round(_fill_pole(wst[name]) if name in C.STRAT_FIELDS else xr.open_dataset(C.DATA / "wb2" / name / f"{y}.nc")[name]).sel(time=sl)
        a = _round(a_all[name].rename(dict(zip(DIMS.get(name, ("lat", "lon")), ("lat", "lon"))))).sel(lat=w.lat, lon=w.lon).values
        d = a - w.values
        ok = np.isfinite(d)
        rows.append(dict(field=name, n_day=int(w.time.size), bias=float(d[ok].mean()),
                         rmse=float(np.sqrt((d[ok] ** 2).mean())), wb2_std=float(np.nanstd(w.values)),
                         corr=float(np.corrcoef(a[ok], w.values[ok])[0, 1])))
        if name in C.PRECIP_FIELDS:
            # 일 누적의 시각 기준 점검: ARCO 일합(그날 00~23 UTC 시각값의 합)을 WB2와 하루 앞뒤로 어긋나게 맞춰 본다.
            # 같은 날(lag 0)의 상관이 가장 높아야 두 자료의 날짜 기준이 같다는 뜻이다
            wv = w.values
            for lag in (-1, 1):
                xa, yw = (a[lag:], wv[:-lag]) if lag > 0 else (a[:lag], wv[-lag:])   # lag=+1: ARCO 다음 날 vs WB2 그날
                dd = xa - yw
                rows.append(dict(field=f"{name}_lag{lag:+d}", n_day=int(xa.shape[0]), bias=float(dd.mean()),
                                 rmse=float(np.sqrt((dd ** 2).mean())), wb2_std=float(np.nanstd(yw)),
                                 corr=float(np.corrcoef(xa.ravel(), yw.ravel())[0, 1])))
    wu, au = wst.u1060.sel(time=sl).values, a_all.u1060.values
    rows.append(dict(field="u1060", n_day=len(wu), bias=float((au - wu).mean()),
                     rmse=float(np.sqrt(((au - wu) ** 2).mean())), wb2_std=float(wu.std()),
                     corr=float(np.corrcoef(au, wu)[0, 1])))
    wp = xr.concat([wst.pcap, xr.open_dataset(C.DATA / "wb2" / "pcap" / f"{y}.nc").pcap], "level")
    dp = a_all.pcap.sel(level=C.PCAP_LEVELS).values - wp.sel(level=C.PCAP_LEVELS, time=sl).values
    for i, lev in enumerate(C.PCAP_LEVELS):
        rows.append(dict(field=f"pcap{lev}", n_day=dp.shape[0], bias=float(dp[:, i].mean()),
                         rmse=float(np.sqrt((dp[:, i] ** 2).mean())), wb2_std=np.nan, corr=np.nan))
    df = pd.DataFrame(rows).round(5)
    C.OUT.mkdir(exist_ok=True)
    df.to_csv(C.OUT / "validation_overlap.csv", index=False)
    log.info("겹침 구간 검증표 저장:\n%s", df.to_string(index=False))
    return df
