"""1단계: 자료 수집. 익명 경로(WeatherBench2, Google ARCO-ERA5)를 먼저 쓰고, 키가 필요한 경로는 있으면 쓴다."""
from __future__ import annotations

import datetime as dt
import json
import logging

import numpy as np
import requests
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, box_regrid, box_weights_lat, box_weights_lon, get_logger, has_key

log = get_logger("fetch")
for noisy in ("gcsfs", "fsspec", "fsspec.caching"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=15)
        return True
    except requests.RequestException:
        return False


def land_fraction() -> None:
    """한반도 평균에 쓸 육지 비율(동아시아 1.5° 격자). ARCO-ERA5의 육지-바다 마스크를 상자 평균한다."""
    out = C.DATA / "static" / "landfrac_ea.nc"
    if out.exists():
        return
    from . import arco_raw as A
    g = xr.open_zarr(C.GARCO_ZARR, storage_options=dict(token="anon"), chunks=None)   # 반드시 chunks=None
    lsm = g["land_sea_mask"].sel(time="2020-01-01T00").load().values
    lf = box_regrid(lsm, box_weights_lat(A.LAT_SRC, A.EA_LAT_T), box_weights_lon(A.LON_SRC, A.EA_LON_T))
    da = xr.DataArray(lf, coords=dict(lat=A.EA_LAT_T, lon=A.EA_LON_T), dims=("lat", "lon"), name="landfrac")
    atomic_to_netcdf(da.to_dataset(), out)


def run(end: dt.date | None = None) -> dt.date:
    """자료를 받고 병합한 뒤, 실제로 확보한 마지막 날짜를 돌려준다."""
    from . import arco_ecmwf, arco_raw, kma, merge, noaa, wb2
    status = {
        "CDSAPI_KEY": "있음" if has_key("CDSAPI_KEY") else "없음",
        "KMA_API_KEY": "있음" if has_key("KMA_API_KEY") else
                       ("없음 (같은 용도의 KMA_AUTHKEY 있음)" if has_key("KMA_AUTHKEY") else "없음"),
        "storage.googleapis.com": "도달" if _reachable("https://storage.googleapis.com/weatherbench2/") else "차단",
        "arco.datastores.ecmwf.int": "도달" if _reachable(C.ECMWF_ARCO) else "차단",
        "apihub.kma.go.kr": "도달" if _reachable(C.KMA_HUB) else "차단",
    }
    log.info("사전 점검: %s", status)
    wb2.run()
    latest = arco_raw.latest_complete_date()
    if end is None or end > latest:
        if end is not None:
            log.warning("요청한 끝 날짜 %s 자료가 아직 없어 %s까지로 줄인다", end, latest)
        google_end = latest
    else:
        google_end = end
    arco_raw.run(google_end)
    final = google_end
    status["ECMWF ARCO"] = "쓰지 않음 (키 없음 또는 도메인 차단)"
    if has_key("CDSAPI_KEY") and status["arco.datastores.ecmwf.int"] == "도달":
        try:
            cov = arco_ecmwf.coverage()
            status["ECMWF ARCO 범위"] = cov
            if end is None or end > google_end:
                want = end or dt.date.fromisoformat(cov["pl_end"][:10])
                final = arco_ecmwf.extend(google_end, want)
            chk = arco_ecmwf.cross_check(min(final, dt.date.fromisoformat(cov["pl_end"][:10])) - dt.timedelta(days=1))
            status["ECMWF ARCO 교차 검증"] = chk
            status["ECMWF ARCO"] = (f"보충 {google_end} → {final}" if final > google_end else
                                    f"보충 없음: 기압면 {cov['pl_end']}까지, 층 {cov['levels'][-1]}~{cov['levels'][0]} hPa "
                                    "(10·30 hPa 없음). Google 원시 자료가 더 최근이다. 겹치는 날로 교차 검증만 함")
        except Exception as e:      # 키가 틀렸거나 저장소 구조가 바뀐 경우. 예외 문자열에 키는 들어가지 않는다
            status["ECMWF ARCO"] = f"실패: {type(e).__name__}"
    land_fraction()
    status["KMA ASOS"] = kma.run(final) if status["apihub.kma.go.kr"] == "도달" \
        else "건너뜀: apihub.kma.go.kr 차단"
    status["NOAA ONI"] = noaa.run()
    merge.build(final)
    status["자료 끝 날짜"] = str(final)
    status["Google ARCO-ERA5 원시 자료 끝"] = str(latest)
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "fetch_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
    return final
