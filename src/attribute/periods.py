"""기간 단위별(반순·주·월·최근 7일·최근 30일) 진단과 인자별 기여도.

기간마다 같은 산출물을 낸다.
- 지수값과 동아시아 하위 영역 기온·강수: 평년(1991~2020) 기준 σ, 1979년 이후 같은 날짜 대비 백분위·순위
- 다중회귀 기여도: 해마다 같은 날짜(와 앞뒤로 옮긴 창)의 같은 길이 창 평균으로 학습, 대상 해는 학습에서 뺀다.
  교차검증 R²(해 단위로 빼고 예측)와 부트스트랩 5~95% 구간
- 동아시아 격자별 기여도 지도 (같은 회귀를 격자마다)
진행 중인 기간은 자료가 있는 날짜까지만 쓴다(창 길이 = 포함된 날짜 수).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from .. import kma_official as K
from .. import narrative as N
from ..common import anomaly, field_clim, get_logger, open_field
from ..periods import Period, same_dates_other_years, standing
from .regression import FACTOR_LABEL

log = get_logger("attribute.periods")

INDEX_KEYS = ["ural", "blocked", "u1060", "pv", "t10_cap_anom", "vt100_anom", "pch10", "pch100", "pch500", "nino34",
              "ao", "nao", "pna", "wp", "eu", "scand", "siberian_high", "aleutian", "ea_jet", "eawm", "phil_sea", "bk_ice"]
TELE = ["ao", "nao", "pna", "wp", "eu", "scand"]
N_BOOT_P = 400


def targets() -> list[tuple[str, str, str, str]]:
    """(열 이름, 영역 키, 변수, 단위)"""
    out = []
    for key in C.EA_SUBREGIONS:
        out.append((f"{key}_t", key, "t", "°C"))
        out.append((f"{key}_p", key, "p", "mm/일"))
    return out


class Windows:
    """누적합으로 임의 창의 평균을 빠르게 구한다 (일별 연속 색인 가정)."""

    def __init__(self, index: pd.DatetimeIndex, arr: np.ndarray):
        self.index = index
        a = np.asarray(arr, dtype="float64")
        a = a.reshape(len(index), -1)
        self.cs = np.vstack([np.zeros((1, a.shape[1])), np.nancumsum(a, 0)])
        self.cn = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(np.isfinite(a), 0)])

    def mean(self, end_pos: np.ndarray, n: int, lag: int = 0) -> np.ndarray:
        e = end_pos - lag + 1
        s = e - n
        cnt = self.cn[e] - self.cn[s]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cnt >= 0.8 * n, (self.cs[e] - self.cs[s]) / cnt, np.nan)


def sample_ends(index: pd.DatetimeIndex, end: pd.Timestamp, n: int, offsets) -> pd.DataFrame:
    rows = []
    first, last = index[0], index[-1]
    max_lag = max(C.DRIVERS.values())
    for y in range(first.year, last.year + 1):
        try:
            base = end.replace(year=y)
        except ValueError:
            base = pd.Timestamp(y, 2, 28)
        for off in offsets:
            e = base + pd.Timedelta(days=off)
            if e - pd.Timedelta(days=n - 1 + max_lag) < first or e > last:
                continue
            rows.append((y, off, e))
    df = pd.DataFrame(rows, columns=["group", "offset", "end"])
    df["pos"] = index.get_indexer(df.end)
    df["is_target"] = (df.group == end.year) & (df.offset == 0)
    return df


def _fit(X, Y):
    A = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(A, Y, rcond=None)[0]


def regress(X: np.ndarray, Y: np.ndarray, groups: np.ndarray, xt: np.ndarray, rng, n_boot: int = N_BOOT_P) -> dict:
    """X: 표본 x 인자, Y: 표본 x 목표(여러 개), xt: 대상 기간 인자값. 표준화 회귀 기여도."""
    ok = np.isfinite(X).all(1)
    X, Y, groups = X[ok], Y[ok], groups[ok]
    mu, sd = X.mean(0), X.std(0, ddof=1)
    Z = (X - mu) / sd
    zt = (xt - mu) / sd
    b = _fit(Z, Y)
    pred = b[0] + zt @ b[1:]
    contrib = b[1:] * zt[:, None]
    yhat = b[0] + Z @ b[1:]
    ss = ((Y - Y.mean(0)) ** 2).sum(0)
    r2 = 1 - ((Y - yhat) ** 2).sum(0) / ss
    cv = np.full_like(Y, np.nan)
    ug = np.unique(groups)
    for g in ug:
        te = groups == g
        m2, s2 = X[~te].mean(0), X[~te].std(0, ddof=1)
        bb = _fit((X[~te] - m2) / s2, Y[~te])
        cv[te] = bb[0] + ((X[te] - m2) / s2) @ bb[1:]
    r2cv = 1 - ((Y - cv) ** 2).sum(0) / ss
    out = dict(b=b, zt=zt, pred=pred, contrib=contrib, r2=r2, r2cv=r2cv, n=int(len(Y)), n_years=int(len(ug)),
               resid_sd=np.sqrt(((Y - yhat) ** 2).sum(0) / (len(Y) - X.shape[1] - 1)))
    if n_boot:
        pos = {g: np.flatnonzero(groups == g) for g in ug}
        bs = np.empty((n_boot,) + contrib.shape)
        for i in range(n_boot):
            idx = np.concatenate([pos[g] for g in rng.choice(ug, len(ug))])
            Xs = X[idx]
            m2, s2 = Xs.mean(0), Xs.std(0, ddof=1)
            bb = _fit((Xs - m2) / s2, Y[idx])
            bs[i] = bb[1:] * ((xt - m2) / s2)[:, None]
        out["lo"], out["hi"] = np.percentile(bs, 5, 0), np.percentile(bs, 95, 0)
    return out


class Engine:
    """기간 분석에 필요한 일별 자료를 한 번 읽어 둔다."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.idx = df.index
        self.factors = list(C.DRIVERS)
        drv = df[[f for f in self.factors if f != "trend"]]
        self.w_drv = {f: Windows(self.idx, drv[f].values) for f in drv}
        self.tcols = [t[0] for t in targets()]
        self.w_tgt = Windows(self.idx, df[self.tcols].values)
        # 동아시아 격자 편차 (기온, 강수)
        self.grid = {}
        for name in ("t2m", "tp"):
            da = open_field(name).load()
            an = anomaly(da, field_clim(name)).sel(time=self.idx)
            self.grid[name] = (an.lat.values, an.lon.values, Windows(self.idx, an.values.reshape(len(self.idx), -1)))

    def design(self, ends: pd.DataFrame, n: int) -> np.ndarray:
        cols = []
        for f in self.factors:
            if f == "trend":
                e = pd.DatetimeIndex(ends.end)
                cols.append(e.year + (e.dayofyear - n / 2) / 365.25)
            else:
                cols.append(self.w_drv[f].mean(ends.pos.values, n, C.DRIVERS[f])[:, 0])
        return np.column_stack(cols)

    def attribution(self, start: pd.Timestamp, eff_end: pd.Timestamp, rng, grid: bool = True) -> dict:
        n = (eff_end - start).days + 1
        offsets = (-21, -14, -7, 0, 7, 14, 21) if n <= 10 else (-30, -15, 0, 15, 30)
        ends = sample_ends(self.idx, eff_end, n, offsets)
        X = self.design(ends, n)
        Y = self.w_tgt.mean(ends.pos.values, n)
        tgt = ends.is_target.values
        train = ~(ends.group.values == eff_end.year)
        ok = train & np.isfinite(Y).all(1)
        res = regress(X[ok], Y[ok], ends.group.values[ok], X[tgt][0], rng)
        out = {}
        for j, (col, reg, var, unit) in enumerate(targets()):
            obs = float(Y[tgt][0, j])
            facs = []
            for i, f in enumerate(self.factors):
                facs.append(dict(factor=f, label=FACTOR_LABEL[f], lag_days=C.DRIVERS[f], z=float(res["zt"][i]),
                                 coef=float(res["b"][i + 1, j]), contribution=float(res["contrib"][i, j]),
                                 lo=float(res["lo"][i, j]), hi=float(res["hi"][i, j]),
                                 verdict=N.ci_word(res["lo"][i, j], res["hi"][i, j])))
            pred = float(res["pred"][j])
            out[col] = dict(observed=obs, predicted=pred, residual=obs - pred, r2=float(res["r2"][j]),
                            r2_cv=float(res["r2cv"][j]), resid_sd=float(res["resid_sd"][j]), n_samples=res["n"],
                            n_years=res["n_years"], factors=facs, unit=unit, region=reg, var=var)
        maps = {}
        if grid:
            for name in ("t2m", "tp"):
                lat, lon, w = self.grid[name]
                G = w.mean(ends.pos.values, n)
                okg = ok & np.isfinite(G).all(1)
                r = regress(X[okg], G[okg], ends.group.values[okg], X[tgt][0], rng, n_boot=0)
                shape = (lat.size, lon.size)
                maps[name] = dict(lat=lat, lon=lon, obs=G[tgt][0].reshape(shape),
                                  contrib={f: r["contrib"][i].reshape(shape) for i, f in enumerate(self.factors)},
                                  resid=(G[tgt][0] - r["pred"]).reshape(shape), r2cv=r["r2cv"].reshape(shape))
        return dict(targets=out, maps=maps, n_days=n, offsets=list(offsets))


def standings(df: pd.DataFrame, start: pd.Timestamp, eff_end: pd.Timestamp, keys) -> dict:
    out = {}
    for k in keys:
        if k not in df:
            continue
        hist = same_dates_other_years(df[k], start.date(), eff_end.date())
        if len(hist) < 10:
            continue
        out[k] = standing(hist)
    return out


def precip_ratio(df: pd.DataFrame, reg: str, start, eff_end) -> float:
    raw = "korea_p_raw" if reg == "korea" else f"{reg}_p_raw"
    clim = "korea_p_clim" if reg == "korea" else f"{reg}_p_clim"
    w = df[start:eff_end]
    return float(w[raw].sum() / w[clim].sum() * 100)


def official_month(df: pd.DataFrame, p: Period, info: dict) -> dict | None:
    """끝난 달력 월이면 ASOS 전국 62개 지점 월값을 기상청 공식 평년비슷범위로 판정한다 (kmahub와 같은 기준)."""
    if p.kind != "month" or not info["complete"] or "asos_t_raw" not in df:
        return None
    w = df[str(p.start):str(p.end)]
    if w["asos_t_raw"].isna().any() or w["asos_p_raw"].isna().any():
        return None
    m = p.start.month
    return dict(tavg=K.classify_tavg(m, float(w["asos_t_raw"].mean())),
                precip=K.classify_precip(m, float(w["asos_p_raw"].sum())))


def analyze_period(eng: Engine, p: Period, data_end: dt.date, rng, grid: bool = True) -> dict:
    df = eng.df
    start, eff_end = pd.Timestamp(p.start), pd.Timestamp(p.eff_end(data_end))
    info = p.info(data_end)
    st_idx = standings(df, start, eff_end, INDEX_KEYS)
    st_tgt = standings(df, start, eff_end, [t[0] for t in targets()] + ["asos_t", "asos_p"])
    att = eng.attribution(start, eff_end, rng, grid=grid)
    regions = []
    for key, (name, _) in C.EA_SUBREGIONS.items():
        t, pp = st_tgt.get(f"{key}_t"), st_tgt.get(f"{key}_p")
        regions.append(dict(key=key, name=name, t=t, p=pp, p_ratio=precip_ratio(df, key, start, eff_end),
                            t_word=N.temp_word(t["sigma"]), p_word=N.precip_word(pp["sigma"])))
    sent = []
    for r in regions:
        sent.append(f"{r['name']}: 기온 {N.standing_phrase(r['t'], '°C')} → {r['t_word']}; 강수 평년비 {r['p_ratio']:.0f}% "
                    f"({N.num(r['p']['sigma'], 1, 'σ')}) → {r['p_word']}.")
    tele = sorted(((k, st_idx[k]) for k in TELE if k in st_idx), key=lambda kv: -abs(kv[1]["sigma"]))
    if tele:
        strong = [f"{C.TELE_LABEL[k]} {v['sigma']:+.1f}σ" for k, v in tele if abs(v["sigma"]) >= C.SIGMA_WEAK]
        sent.append("원격상관 패턴(일별 지수 기간 평균의 σ, 큰 순): " + ", ".join(
            f"{C.TELE_LABEL[k]} {v['sigma']:+.1f}σ" for k, v in tele) +
            (". |σ| ≥ 0.5인 패턴: " + ", ".join(strong) + "." if strong else ". |σ| ≥ 0.5인 패턴은 없다."))
    for col in ("korea_t", "ea_t", "korea_p"):
        name = C.EA_SUBREGIONS[col.split("_")[0]][0] + (" 기온" if col.endswith("_t") else " 강수")
        a = att["targets"][col]
        sent.append(N.contribution_sentence(name, a, a["unit"]))
    if "asos_t" in st_tgt:
        a, e = st_tgt["asos_t"], st_tgt["korea_t"]
        sent.append(f"관측 검증: ASOS 전국 평균 기온 편차 {N.num(a['value'], 2, '°C')}({N.num(a['sigma'], 1, 'σ')}), "
                    f"ERA5 한반도 {N.num(e['value'], 2, '°C')}({N.num(e['sigma'], 1, 'σ')})."
                    + (" 두 자료의 판정 등급이 다르다." if N.temp_word(a["sigma"]) != N.temp_word(e["sigma"]) else ""))
    kma = official_month(df, p, info)
    if kma:
        t, r = kma["tavg"], kma["precip"]
        sent.append(f"기상청 공식 판정(전국 62개 지점, 1991~2020 평년비슷범위): 평균기온 {t['observed']:.1f}°C, "
                    f"평년 대비 {t['departure']:+.1f}°C({t['sign']}, 비슷범위 ±{t['half_range']:.1f}) → {t['word']}; "
                    f"강수량 {r['observed']:.1f} mm, 평년비 {r['ratio']:.0f}%({r['sign']}, 비슷범위 "
                    f"{r['lower']:.1f}~{r['upper']:.1f} mm) → {r['word']}.")
    if not info["complete"]:
        sent.insert(0, f"진행 중인 기간이다: {info['full_days']}일 중 {info['n_days']}일({info['eff_end']}까지)만 포함했다.")
    return dict(period=info, indices=st_idx, regions=regions, attribution=att, sentences=sent, kma_official=kma,
                blocked_days=int(df.blocked[start:eff_end].sum()))


def r2_by_kind(results: list[dict]) -> list[dict]:
    """기간 단위별 설명력: 단위마다 가장 최근 기간의 교차검증 R²."""
    rows, seen = [], set()
    for r in results:
        k = r["period"]["kind"]
        if k in seen:
            continue
        seen.add(k)
        a = r["attribution"]["targets"]
        rows.append(dict(kind=k, kind_label=r["period"]["kind_label"], pid=r["period"]["pid"], n_days=r["period"]["n_days"],
                         **{f"r2cv_{c}": a[c]["r2_cv"] for c in ("korea_t", "korea_p", "ea_t", "ea_p")},
                         **{f"r2_{c}": a[c]["r2"] for c in ("korea_t", "ea_t")}))
    return rows
