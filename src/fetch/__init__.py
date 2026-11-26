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


def _reachable(url: str, tries: int = 3) -> bool:
    """도메인 도달 여부. 응답이 느린 서버(KMA 허브)가 있어 시간을 넉넉히 주고 몇 번 다시 본다."""
    for _ in range(tries):
        try:
            requests.get(url, timeout=40)
            return True
        except requests.RequestException:
            continue
    return False


def land_fraction() -> None:
    """육지 비율(1.5° 격자). ARCO-ERA5의 육지-바다 마스크를 상자 평균한다.

    landfrac_ea.nc: 동아시아 영역(한반도·하위 영역 평균용), landfrac_nh.nc: 북반구(강제인자 육지 지수, 모식도 육지 기온용).
    """
    from . import arco_raw as A
    outs = {"ea": (C.DATA / "static" / "landfrac_ea.nc", A.EA_LAT_T, A.EA_LON_T),
            "nh": (C.DATA / "static" / "landfrac_nh.nc", C.LAT_NH, C.LON)}
    if all(p.exists() for p, _, _ in outs.values()):
        return
    g = xr.open_zarr(C.GARCO_ZARR, storage_options=dict(token="anon"), chunks=None)   # 반드시 chunks=None
    lsm = g["land_sea_mask"].sel(time="2020-01-01T00").load().values
    for out, lat, lon in outs.values():
        if out.exists():
            continue
        lf = box_regrid(lsm, box_weights_lat(A.LAT_SRC, lat), box_weights_lon(A.LON_SRC, lon))
        da = xr.DataArray(lf, coords=dict(lat=lat, lon=lon), dims=("lat", "lon"), name="landfrac")
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
    from . import cds_monthly
    status["CDS 월평균 지면온도"] = cds_monthly.run(wait=False)   # CDS 요청 1건. 끝난 뒤에 다음 CDS 요청(최근 날짜 보충)을 넣는다
    cds_free = not cds_monthly.busy()                              # 아직 대기열에 있으면 이번 실행에서는 CDS를 더 쓰지 않는다
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
                # Google에 일부만 올라온 최근 날짜: 빠진 항목을 ECMWF ARCO, 그래도 없으면 CDS API(한 건씩)로 채운다
                filled = []
                d = google_end + dt.timedelta(days=1)
                while (end is None or d <= end) and d < dt.datetime.now(dt.timezone.utc).date():
                    r = arco_ecmwf.fill_partial(d, use_cds=cds_free)
                    if r is None:
                        break
                    filled.append(r)
                    final = d
                    d += dt.timedelta(days=1)
                if filled:
                    status["최근 날짜 혼합 채움"] = filled
                want = end or dt.date.fromisoformat(cov["pl_end"][:10])
                final = arco_ecmwf.extend(final, want)
            chk = arco_ecmwf.cross_check(google_end)      # Google 자료만으로 만든 마지막 날로 비교한다
            status["ECMWF ARCO 교차 검증"] = chk
            status["ECMWF ARCO"] = (f"기압면 {cov['pl_end']}까지, 층 {cov['levels'][-1]}~{cov['levels'][0]} hPa(10·30 hPa 없음), "
                                    f"해빙 없음. Google 완결 자료({google_end}) 뒤 {final}까지 빠진 항목 보충, 겹치는 날 교차 검증")
        except Exception as e:      # 키가 틀렸거나 저장소 구조가 바뀐 경우. 예외 문자열에 키는 들어가지 않는다
            status["ECMWF ARCO"] = f"실패: {type(e).__name__}"
    land_fraction()
    # 도달 점검이 실패해도 키가 있으면 시도한다 (점검 요청만 끊기는 경우가 있다)
    status["KMA ASOS"] = kma.run(final)
    status["NOAA ONI"] = noaa.run()
    merge.build(final)
    status["자료 끝 날짜"] = str(final)
    status["Google ARCO-ERA5 원시 자료 끝"] = str(latest)
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "fetch_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
    return final
