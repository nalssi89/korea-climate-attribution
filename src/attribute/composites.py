"""시차 합성도: 우랄블로킹 발생일, SSW 중심일, 엔소 겨울 기준. 신뢰구간은 사건(겨울) 단위 부트스트랩."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C


def _boot_ci(mat: np.ndarray, rng: np.random.Generator, n_boot: int = C.N_BOOT):
    """행 = 사건, 열 = 시차. 사건을 복원추출해 평균의 5~95% 구간을 구한다."""
    n = mat.shape[0]
    idx = rng.integers(0, n, size=(n_boot, n))
    means = np.nanmean(mat[idx], axis=1)
    return np.nanpercentile(means, 5, axis=0), np.nanpercentile(means, 95, axis=0)


def lag_composite(series: pd.Series, dates, lags: np.ndarray, rng) -> pd.DataFrame:
    """사건 날짜 기준 시차별 평균과 신뢰구간. 자료 범위를 벗어난 시차는 NaN으로 둔다."""
    s = series.dropna()
    rows = []
    for d in pd.DatetimeIndex(dates):
        rows.append(s.reindex(d + pd.to_timedelta(lags, unit="D")).values)
    mat = np.array(rows, dtype="float64")
    lo, hi = _boot_ci(mat, rng)
    return pd.DataFrame({"lag": lags, "mean": np.nanmean(mat, 0), "lo": lo, "hi": hi,
                         "n": np.isfinite(mat).sum(0)})


def window_stat(series: pd.Series, dates, lag0: int, lag1: int, rng) -> dict:
    """사건별 [lag0, lag1]일 평균의 사건 평균과 신뢰구간."""
    s = series.dropna()
    vals = np.array([s.reindex(pd.date_range(d + pd.Timedelta(days=lag0), d + pd.Timedelta(days=lag1))).mean()
                     for d in pd.DatetimeIndex(dates)])
    vals = vals[np.isfinite(vals)]
    bs = rng.choice(vals, size=(C.N_BOOT, len(vals))).mean(1)
    return dict(mean=float(vals.mean()), lo=float(np.percentile(bs, 5)), hi=float(np.percentile(bs, 95)),
                n=int(len(vals)), frac_neg=float((vals < 0).mean()))


def enso_monthly(mon: pd.DataFrame, phases: pd.DataFrame, rng) -> pd.DataFrame:
    """엘니뇨/라니냐/중립 겨울의 월별(11~3월) 한반도 기온·강수 편차 평균과 신뢰구간.

    mon: 월평균(색인 = 달 첫날), phases: enso.winter_phase 결과 (색인 = 겨울의 1월이 속한 해).
    """
    rows = []
    for m in (11, 12, 1, 2, 3):
        for ph in ("엘니뇨", "라니냐", "중립"):
            yrs = phases.index[phases.phase == ph]
            for var in mon.columns:
                vals = []
                for y in yrs:
                    t = pd.Timestamp(y - 1 if m >= 11 else y, m, 1)
                    if t in mon.index and np.isfinite(mon.at[t, var]):
                        vals.append(mon.at[t, var])
                vals = np.array(vals)
                if len(vals) < 3:
                    continue
                bs = rng.choice(vals, size=(C.N_BOOT, len(vals))).mean(1)
                rows.append(dict(month=m, phase=ph, var=var, mean=vals.mean(), lo=np.percentile(bs, 5),
                                 hi=np.percentile(bs, 95), n=len(vals)))
    return pd.DataFrame(rows)
