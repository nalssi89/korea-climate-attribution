"""CDS 작업 목록 조회와 이어받기.

CDS 대기열은 몇 시간씩 걸려서, 기다리던 프로세스가 컨테이너 재시작으로 끊기는 일이 잦다.
같은 요청을 다시 넣으면 'CDS 요청은 한 번에 1건' 규칙이 깨지므로, 이미 넣은 작업을 찾아 이어받는다.
키는 환경변수 CDSAPI_KEY에서만 읽고, 로그·예외 문자열에 넣지 않는다.
"""
from __future__ import annotations

import os
import time

from ..common import get_logger

log = get_logger("fetch.cds_jobs")
API = "https://cds.climate.copernicus.eu/api/retrieve/v1"
LIVE = ("accepted", "running")


def _get(path: str, **kw):
    import requests
    r = requests.get(f"{API}/{path}", headers={"PRIVATE-TOKEN": os.environ["CDSAPI_KEY"]}, timeout=60, **kw)
    r.raise_for_status()
    return r.json()


def status(jid: str) -> str:
    return _get(f"jobs/{jid}")["status"]


def pending() -> list[str]:
    """아직 끝나지 않은(대기·실행 중) 작업 번호. 조회가 안 되면 빈 목록."""
    try:
        return [j["jobID"] for j in _get("jobs", params={"limit": 20}).get("jobs", []) if j.get("status") in LIVE]
    except Exception as e:
        log.warning("CDS 작업 목록 조회 실패: %s", type(e).__name__)
        return []


def _norm(v):
    return sorted(map(str, v)) if isinstance(v, list) else [str(v)]


def find(dataset: str, req: dict) -> str | None:
    """dataset과 req의 항목(값 순서 무시)이 모두 같은, 대기·실행 중이거나 성공한 작업 번호."""
    try:
        jobs = _get("jobs", params={"limit": 20}).get("jobs", [])
    except Exception as e:      # 목록 조회가 안 되면 새 요청 경로로 간다
        log.warning("CDS 작업 목록 조회 실패: %s", type(e).__name__)
        return None
    for j in jobs:
        if j.get("processID") != dataset or j.get("status") not in LIVE + ("successful",):
            continue
        try:
            got = _get(f"jobs/{j['jobID']}", params={"request": "true"})["metadata"]["request"]["ids"]
        except Exception:
            continue
        if all(_norm(got.get(k)) == _norm(v) for k, v in req.items()):
            return j["jobID"]
    return None


def wait(jid: str, dest, max_wait_s: int = 6 * 3600) -> None:
    """이미 넣은 CDS 작업이 끝날 때까지 기다렸다가 결과 파일을 dest로 받는다."""
    import requests
    t0 = time.time()
    while True:
        st = status(jid)
        if st == "successful":
            break
        if st in ("failed", "rejected", "dismissed", "deleted"):
            raise RuntimeError(f"CDS 작업 상태 {st}")
        if time.time() - t0 > max_wait_s:
            raise TimeoutError("CDS 작업이 끝나지 않았다")
        time.sleep(60)
    href = _get(f"jobs/{jid}/results")["asset"]["value"]["href"]
    with requests.get(href, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
