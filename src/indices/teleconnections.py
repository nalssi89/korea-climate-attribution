"""북반구 원격상관 패턴: 겨울철(11~3월) 월평균 Z500 편차의 회전(varimax) EOF.

1. 20°N 이북 Z500 일별 편차를 3° 간격으로 솎고 √cos(위도) 가중을 준다.
2. 1979~2020년 11~3월 월평균으로 앞쪽 10개 EOF를 구해 varimax로 회전한다.
3. 회전 모드마다 문헌의 활동 중심(config.TELE_TEMPLATES)과 맞춰 보고, 가장 잘 맞는 모드를 그 패턴으로 정한다.
   맞춤 점수(활동 중심에서 부호를 곱한 적재값의 평균을 적재값 최대 크기로 나눈 값)를 함께 남긴다.
4. 일별 편차를 회전 모드 전체에 최소제곱으로 투영해 일별 지수를 만들고, 평년 기간 표준편차로 나눈다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import anomaly, daily_clim, get_logger

log = get_logger("indices.tele")


def varimax(L: np.ndarray, gamma: float = 1.0, iters: int = 100, tol: float = 1e-8) -> np.ndarray:
    """적재 행렬 L(변수 x 모드)의 varimax 회전 행렬."""
    p, k = L.shape
    R = np.eye(k)
    d = 0.0
    for _ in range(iters):
        Lr = L @ R
        u, s, vt = np.linalg.svd(L.T @ (Lr ** 3 - (gamma / p) * Lr @ np.diag((Lr ** 2).sum(0))))
        R = u @ vt
        d_new = s.sum()
        if d_new < d * (1 + tol):
            break
        d = d_new
    return R


def _nearest(lat: np.ndarray, lon: np.ndarray, la: float, lo: float) -> int:
    i = int(np.abs(lat - la).argmin())
    j = int(np.abs((lon - lo + 180) % 360 - 180).argmin())
    return i * lon.size + j


def compute(z500: xr.DataArray) -> tuple[pd.DataFrame, dict, xr.DataArray]:
    sub = z500.sel(lat=slice(20, 90)).isel(lat=slice(None, None, 2), lon=slice(None, None, 2))
    anom = anomaly(sub, daily_clim(sub))
    lat, lon = anom.lat.values, anom.lon.values
    w = np.sqrt(np.cos(np.deg2rad(np.clip(lat, None, 89.0))))[:, None] * np.ones(lon.size)
    X = (anom.values * w).reshape(anom.sizes["time"], -1)
    t = pd.DatetimeIndex(anom.time.values)
    base = (t.year >= C.START_YEAR) & (t.year <= C.CLIM[1]) & t.month.isin(C.TELE_MONTHS)
    mon = pd.DataFrame(X[base]).groupby([t[base].year, t[base].month]).mean().values
    mon = mon - mon.mean(0)
    _, s, vt = np.linalg.svd(mon, full_matrices=False)
    k = C.TELE_NMODES
    var_frac = s ** 2 / (s ** 2).sum()
    L = vt[:k].T * s[:k] / np.sqrt(mon.shape[0] - 1)        # 변수 x 모드 (단위: m)
    Lr = L @ varimax(L)
    # 활동 중심 맞춤: 점수가 큰 짝부터 하나씩 배정한다
    scores = {}
    for name, cen in C.TELE_TEMPLATES.items():
        idx = [_nearest(lat, lon, la, lo) for la, lo, _ in cen]
        sg = np.array([sgn for *_, sgn in cen])
        scores[name] = (Lr[idx] * sg[:, None]).mean(0) / np.abs(Lr).max(0)
    assign, used = {}, set()
    pairs = sorted(((abs(v), n, m) for n, sc in scores.items() for m, v in enumerate(sc)), reverse=True)
    for sc, n, m in pairs:
        if n not in assign and m not in used:
            assign[n] = m
            used.add(m)
    # 일별 투영 (회전 모드 전체에 최소제곱)
    pcs = X @ np.linalg.pinv(Lr).T
    base_d = (t.year >= C.CLIM[0]) & (t.year <= C.CLIM[1]) & t.month.isin(C.TELE_MONTHS)
    out = pd.DataFrame(index=t)
    meta = {}
    rot_var = (Lr ** 2).sum(0) / (np.linalg.norm(mon, axis=1) ** 2).sum() * (mon.shape[0] - 1)
    patterns = {}
    for n, m in assign.items():
        sign = 1.0 if scores[n][m] > 0 else -1.0
        pc = sign * pcs[:, m]
        out[n] = pc / pc[base_d].std()
        patterns[n] = sign * Lr[:, m].reshape(lat.size, lon.size) / w
        meta[n] = dict(mode=int(m + 1), match=float(abs(scores[n][m])), var_frac=float(rot_var[m]))
    meta["_unrotated_var_frac"] = [float(v) for v in var_frac[:k]]
    # 점 지수와의 상관으로 맞춤을 점검한다 (Wallace & Gutzler 1981의 PNA 점 지수)
    za = anom
    pna_pt = 0.25 * (za.sel(lat=21, lon=201, method="nearest") - za.sel(lat=45, lon=195, method="nearest")
                     + za.sel(lat=54, lon=246, method="nearest") - za.sel(lat=30, lon=276, method="nearest")).to_series()
    if "pna" in out:
        m = out.index.month.isin(C.TELE_MONTHS)
        meta["pna"]["corr_point_index"] = float(out.loc[m, "pna"].corr(pna_pt[m]))
    pat = xr.DataArray(np.stack([patterns[n] for n in out.columns]), dims=("pattern", "lat", "lon"),
                       coords=dict(pattern=list(out.columns), lat=lat, lon=lon), name="loading")
    log.info("원격상관 패턴: %s", {n: (v["mode"], round(v["match"], 2)) for n, v in meta.items() if not n.startswith("_")})
    return out.astype("float32"), meta, pat


def save_meta(meta: dict) -> None:
    (C.OUT / "teleconnection_modes.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
