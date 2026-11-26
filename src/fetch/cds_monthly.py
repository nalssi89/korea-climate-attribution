"""CDS API 1건: ERA5 월평균 지면온도(skin temperature)와 1층 토양온도(0~7 cm), 1979년~최근, 북반구 1.5°.

WeatherBench2 일평균에는 지면온도가 없어서, 강제인자 분석의 '지면온도' 항목만 이 월평균 자료로 만든다.
요청은 한 건뿐이고, 다른 CDS 요청과 겹치지 않게 fetch.run에서 순서대로 부른다.
이미 받은 파일이 있으면 다시 받지 않는다. 다만 파일의 마지막 달이 너무 오래됐으면(90일 넘게) 새로 받는다.
같은 요청이 이미 CDS 대기열에 있으면(컨테이너가 다시 시작돼 기다리던 프로세스가 끊긴 경우) 새로 넣지 않고 그 작업을 이어 받는다.
"""
from __future__ import annotations

import datetime as dt
import os

import numpy as np
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, get_logger, has_key
from . import cds_jobs

log = get_logger("fetch.cds_monthly")
RAW = C.DATA / "cds" / "monthly_skt_stl1_raw.nc"
LOCK = C.DATA / "cds" / "monthly_skt_stl1.lock"      # 요청 중인 프로세스 번호. CDS 요청이 겹치지 않게 한다
OUT = C.DATA / "cds" / "monthly_skt_stl1.nc"
DATASET = "reanalysis-era5-single-levels-monthly-means"
VARS = {"skt": "skin_temperature", "stl1": "soil_temperature_level_1"}


def _stale(path, today: dt.date) -> bool:
    with xr.open_dataset(path) as ds:
        last = np.datetime64(ds.time.values[-1], "D").astype(object)
    return (today - last).days > 90


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def busy() -> bool:
    """다른 프로세스가 이 요청을 CDS 대기열에 넣고 기다리는 중인지."""
    try:
        pid = int(LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _alive(pid)


def _wait_other(max_wait_s: int = 7200) -> None:
    """다른 프로세스가 같은 요청을 대기열에 넣고 기다리는 중이면 끝날 때까지 기다린다 (두 번째 요청을 넣지 않는다)."""
    import time
    t0 = time.time()
    while LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
        except ValueError:
            break
        if pid == os.getpid() or not _alive(pid):
            break
        if time.time() - t0 > max_wait_s:
            raise TimeoutError("다른 CDS 월평균 요청이 끝나지 않았다")
        log.info("다른 프로세스(%d)의 CDS 월평균 요청이 끝나기를 기다린다", pid)
        time.sleep(60)
    LOCK.unlink(missing_ok=True)


def run(today: dt.date | None = None, wait: bool = True) -> str:
    """wait=False면 다른 프로세스가 요청 중일 때 기다리지 않고 '요청 중'을 돌려준다 (그동안 다른 CDS 요청도 넣지 않는다)."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if not wait and busy():
        return "요청 중 (다른 프로세스가 CDS 대기열에서 기다리는 중, 다음 실행에서 반영)"
    _wait_other()
    if OUT.exists() and not _stale(OUT, today):
        with xr.open_dataset(OUT) as ds:
            return f"이미 있음 ({str(ds.time.values[0])[:7]}~{str(ds.time.values[-1])[:7]})"
    if not has_key("CDSAPI_KEY"):
        return "건너뜀: CDSAPI_KEY 없음"
    RAW.parent.mkdir(parents=True, exist_ok=True)
    tmp = RAW.with_suffix(".part")
    req = {"product_type": ["monthly_averaged_reanalysis"], "variable": list(VARS.values()),
           "year": [str(y) for y in range(C.START_YEAR, today.year + 1)],
           "month": [f"{m:02d}" for m in range(1, 13)], "time": ["00:00"],
           "area": [90, 0, 0, 358.5], "grid": [1.5, 1.5],
           "data_format": "netcdf", "download_format": "unarchived"}
    # 연도 범위까지 같아야 같은 요청으로 본다. 그래야 해가 바뀐 뒤 지난해 범위로 끝난 작업을 다시 받아 오래된 자료가 남는 일이 없다
    jid = cds_jobs.find(DATASET, {"variable": req["variable"], "grid": req["grid"], "year": req["year"]})
    if jid is not None:
        try:
            done = cds_jobs.status(jid) == "successful"
        except Exception as e:      # 상태 조회가 안 되면 이번 실행에서는 기다리지 않는다
            log.warning("CDS 작업 상태 조회 실패: %s", type(e).__name__)
            done = False
        if not wait and not done:
            return "요청 중 (같은 요청이 CDS 대기열에 있음, 다음 실행에서 반영)"
        LOCK.write_text(str(os.getpid()))
        log.info("이미 넣은 CDS 작업을 이어 기다린다 (새 요청을 넣지 않음)")
        try:
            cds_jobs.wait(jid, tmp)
        except Exception as e:
            log.warning("CDS 월평균 작업 받기 실패: %s", type(e).__name__)
            return f"실패: {type(e).__name__}"
        finally:
            LOCK.unlink(missing_ok=True)
        return _finish(tmp)
    import cdsapi
    cl = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=os.environ["CDSAPI_KEY"], quiet=True, progress=False)
    LOCK.write_text(str(os.getpid()))
    log.info("CDS 요청 1건: %s %s, %d~%d년 월평균, 북반구 1.5°", DATASET, list(VARS), C.START_YEAR, today.year)
    try:
        cl.retrieve(DATASET, req, str(tmp))
    except Exception as e:      # 예외 문자열에 키는 들어가지 않는다
        log.warning("CDS 월평균 요청 실패: %s", type(e).__name__)
        return f"실패: {type(e).__name__}"
    finally:
        LOCK.unlink(missing_ok=True)
    return _finish(tmp)


def _finish(tmp) -> str:
    """받은 원파일을 변수별 lat/lon/time 형태로 정리해 OUT에 쓴다."""
    tmp.rename(RAW)
    ds = xr.open_dataset(RAW)
    tname = "valid_time" if "valid_time" in ds.dims else "time"
    out = xr.Dataset()
    for k in VARS:
        da = ds[k].squeeze(drop=True)
        da = da.rename({tname: "time", "latitude": "lat", "longitude": "lon"})
        da = da.assign_coords(lat=np.round(da.lat.values, 6), lon=np.round(da.lon.values % 360, 6)).sortby("lat").sortby("lon")
        out[k] = da.astype("float32")
    # 월 첫날로 시각을 맞춘다
    out = out.assign_coords(time=out.time.values.astype("datetime64[M]").astype("datetime64[ns]"))
    out = out.dropna("time", how="all")
    atomic_to_netcdf(out, OUT)
    RAW.unlink()
    return f"완료 ({str(out.time.values[0])[:7]}~{str(out.time.values[-1])[:7]})"


if __name__ == "__main__":
    print(run())
