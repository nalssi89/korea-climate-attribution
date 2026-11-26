"""다중회귀로 분석 기간의 인자별 기여도와 잔차를 나눈다.

표본: 해마다 같은 계절의 30일 창(분석 기간과 같은 날짜, 그리고 ±15, ±30일 옮긴 창)의 평균.
예측인자는 표준화하고, 분석 대상 해(겨울)는 학습에서 뺀다. 신뢰구간은 해 단위 부트스트랩.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C

FACTOR_LABEL = {"trend": "장기 추세", "ural": "우랄블로킹", "pv": "성층권 극소용돌이", "nino34": "엔소(Niño3.4)",
                "bk_ice": "바렌츠-카라 해빙"}
LINKS = ["ao", "siberian_high", "ea_jet", "eawm", "phil_sea"]


def window_table(df: pd.DataFrame, end: pd.Timestamp, ndays: int = C.WINDOW_DAYS,
                 offsets=(-30, -15, 0, 15, 30)) -> pd.DataFrame:
    """해·오프셋별 창 평균 표. group은 같은 해의 창들을 묶는 번호(부트스트랩·교차검증 단위)."""
    rows = []
    first, last = df.index[0], df.index[-1]
    max_lag = max(C.DRIVERS.values())
    for y in range(first.year, last.year + 2):
        base_end = end + pd.DateOffset(years=y - end.year)
        for off in offsets:
            e = base_end + pd.Timedelta(days=off)
            s = e - pd.Timedelta(days=ndays - 1)
            if s - pd.Timedelta(days=max_lag) < first or e > last:
                continue
            row = dict(group=y, offset=off, end=e, is_target=(y == end.year and off == 0),
                       korea_t=df.loc[s:e, "korea_t"].mean(), korea_p=df.loc[s:e, "korea_p"].mean())
            for k, lag in C.DRIVERS.items():
                if k == "trend":
                    row[k] = e.year + (e.dayofyear - ndays / 2) / 365.25
                else:
                    lg = pd.Timedelta(days=lag)
                    row[k] = df.loc[s - lg:e - lg, k].mean()
            for k in LINKS:
                row[k] = df.loc[s:e, k].mean()
            rows.append(row)
    return pd.DataFrame(rows)


def _fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def _contrib(train: pd.DataFrame, target: pd.Series, y: str, factors: list[str]) -> tuple[dict, np.ndarray, float]:
    """표준화 회귀 → 인자별 기여도(계수 x 대상 기간의 표준화 값). 추세 기여에는 절편을 합친다."""
    mu, sd = train[factors].mean(), train[factors].std()
    b = _fit(((train[factors] - mu) / sd).values, train[y].values)
    z = ((target[factors] - mu) / sd).values.astype(float)
    c = dict(zip(factors, b[1:] * z))
    c["trend"] = c.get("trend", 0.0) + b[0]
    return c, b, float(b[0] + b[1:] @ z)


def _r2(y, yhat) -> float:
    return float(1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def attribute(tab: pd.DataFrame, y: str, rng: np.random.Generator) -> dict:
    factors = list(C.DRIVERS)
    target = tab[tab.is_target].iloc[0]
    train = tab[tab.group != target.group].dropna(subset=factors + [y])
    joint, b, pred = _contrib(train, target, y, factors)
    mu, sd = train[factors].mean(), train[factors].std()
    Z = ((train[factors] - mu) / sd).values
    r2 = _r2(train[y].values, b[0] + Z @ b[1:])
    # 해 단위로 빼고 예측하는 교차검증
    cv = np.full(len(train), np.nan)
    for g in train.group.unique():
        te = (train.group == g).values
        tr = train[~te]
        m2, s2 = tr[factors].mean(), tr[factors].std()
        bb = _fit(((tr[factors] - m2) / s2).values, tr[y].values)
        cv[te] = bb[0] + ((train[te][factors] - m2) / s2).values @ bb[1:]
    r2_cv = _r2(train[y].values, cv)
    bt = _fit(Z[:, [factors.index("trend")]], train[y].values)
    r2_trend = _r2(train[y].values, bt[0] + Z[:, factors.index("trend")] * bt[1])
    # 부트스트랩 (해 단위 복원추출)
    groups = train.group.unique()
    parts = {g: train[train.group == g] for g in groups}
    boot = {f: [] for f in factors}
    boot_b = {f: [] for f in factors}
    for _ in range(C.N_BOOT):
        smp = pd.concat([parts[g] for g in rng.choice(groups, len(groups))])
        c, bb, _ = _contrib(smp, target, y, factors)
        for i, f in enumerate(factors):
            boot[f].append(c[f])
            boot_b[f].append(bb[i + 1])
    # 인자 하나만 넣은 회귀(추세 + 인자): 인자끼리 얽힌 정도를 범위로 보여 주기 위함
    single = {}
    for f in factors:
        if f != "trend":
            single[f] = _contrib(train, target, y, ["trend", f])[0][f]
    obs = float(target[y])
    rows = []
    for i, f in enumerate(factors):
        vals = [joint[f]] + ([single[f]] if f in single else [])
        rows.append(dict(factor=f, label=FACTOR_LABEL[f], lag_days=C.DRIVERS[f],
                         z=float((target[f] - mu[f]) / sd[f]), coef=float(b[i + 1]),
                         coef_lo=float(np.percentile(boot_b[f], 5)), coef_hi=float(np.percentile(boot_b[f], 95)),
                         contribution=float(joint[f]), lo=float(np.percentile(boot[f], 5)),
                         hi=float(np.percentile(boot[f], 95)),
                         single=float(single[f]) if f in single else None,
                         range_lo=float(min(vals)), range_hi=float(max(vals))))
    return dict(target=y, observed=obs, predicted=pred, residual=obs - pred, r2=r2, r2_cv=r2_cv,
                r2_trend_only=r2_trend, n_samples=int(len(train)), n_years=int(len(groups)),
                resid_sd=float(np.std(train[y].values - (b[0] + Z @ b[1:]), ddof=len(factors) + 1)),
                factors=rows, driver_corr=train[factors].corr().round(2).to_dict())


def links_table(tab: pd.DataFrame) -> list[dict]:
    """연결 고리 인자: 같은 계절 창에서 한반도 기온·강수, 주요 원인 인자와의 상관과 이번 기간의 표준화 값."""
    target = tab[tab.is_target].iloc[0]
    train = tab[tab.group != target.group]
    out = []
    for k in LINKS:
        out.append(dict(index=k, z=float((target[k] - train[k].mean()) / train[k].std()),
                        corr_t=float(train[k].corr(train.korea_t)), corr_p=float(train[k].corr(train.korea_p)),
                        corr_ural=float(train[k].corr(train.ural)), corr_pv=float(train[k].corr(train.pv)),
                        corr_nino34=float(train[k].corr(train.nino34))))
    return out


def monthly_coefficients(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """달별(11~3월)·겨울(DJF) 표준화 회귀계수와 신뢰구간 (계절에 따라 영향이 어떻게 달라지는지)."""
    factors = list(C.DRIVERS)
    specs = [("11월", pd.Timestamp(2001, 11, 30), 30, (-15, 0, 15)), ("12월", pd.Timestamp(2001, 12, 31), 31, (-15, 0, 15)),
             ("1월", pd.Timestamp(2002, 1, 31), 31, (-15, 0, 15)), ("2월", pd.Timestamp(2002, 2, 28), 28, (-15, 0, 15)),
             ("3월", pd.Timestamp(2002, 3, 31), 31, (-15, 0, 15)), ("겨울(DJF)", pd.Timestamp(2002, 2, 28), 90, (0,))]
    rows = []
    for name, end, nd, offs in specs:
        tab = window_table(df, end, nd, offs).dropna(subset=factors + ["korea_t", "korea_p"])
        groups = tab.group.unique()
        parts = {g: tab[tab.group == g] for g in groups}
        for y in ("korea_t", "korea_p"):
            Z = ((tab[factors] - tab[factors].mean()) / tab[factors].std()).values
            b = _fit(Z, tab[y].values)
            r2 = _r2(tab[y].values, b[0] + Z @ b[1:])
            bs = []
            for _ in range(C.N_BOOT // 2):
                s = pd.concat([parts[g] for g in rng.choice(groups, len(groups))])
                bs.append(_fit(((s[factors] - s[factors].mean()) / s[factors].std()).values, s[y].values)[1:])
            bs = np.array(bs)
            for i, f in enumerate(factors):
                rows.append(dict(period=name, target=y, factor=f, coef=b[i + 1], lo=np.percentile(bs[:, i], 5),
                                 hi=np.percentile(bs[:, i], 95), r2=r2, n=len(tab)))
    return pd.DataFrame(rows)
