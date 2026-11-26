"""강제인자 연관성 분석: 해빙, 해수면온도, 눈덮임, 지면온도, 토양수분이 동아시아(한반도 포함) 기온·강수와
북반구 순환(우랄블로킹, AO, 극소용돌이 세기, 100 hPa 열속)에 연관이 있는지 객관적으로 본다.

1) 영역 지수(일별 편차): 정의와 출처는 config.FORCING. 지면온도 월평균(CDS)만 월 단위.
2) 현재 상태: 최근 7일·30일·이번 달·이번 반순 편차를 σ와 백분위로 (1979년 이후 같은 날짜 구간 대비).
3) 과거 시차 상관(1979~지난해): 월평균, 달별 선형 추세 제거, 강제인자가 0~2개월 앞설 때.
   유의성은 해(겨울) 단위 부트스트랩 95% 구간으로 판정하고, 자기상관을 고려한 유효 표본 p값과
   다중검정 보정(Benjamini-Hochberg FDR)을 함께 적는다.
4) 회귀 비교: 기존 회귀 인자(추세, 우랄, 극소용돌이, Niño3.4, 바렌츠-카라 해빙)에 강제인자 하나를
   미리 정한 시차(1개월)로 더했을 때 교차검증 R²가 얼마나 바뀌는지, 이번 달 기여가 얼마인지.

문장은 narrative 규칙대로 수치에서 만든다. 구간이 0을 포함하면 "유의하지 않음"이라고 쓴다.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import xarray as xr
from scipy import stats

from . import config as C
from . import narrative as N
from .common import (anomaly, area_mean, atomic_to_netcdf, field_clim, get_logger, load_indices, lon_mask, open_field,
                     savefig, series_anom, setup_plot)
from .periods import last_n, month_of, pentad, pentad_of, same_dates_other_years, standing

log = get_logger("forcing")
CDS_MONTHLY = C.DATA / "cds" / "monthly_skt_stl1.nc"
WORDS = {"해빙": ("많음", "적음"), "해수면온도": ("높음", "낮음"), "눈덮임": ("넓음", "좁음"), "토양수분": ("습함", "건조함"),
         "지면온도": ("높음", "낮음")}
N_BOOT_CORR = 1000
MONTH_KO = {m: f"{m}월" for m in range(1, 13)}


# ------------------------------------------------------------------ 눈덮임 비율 (눈 깊이에서)
def ensure_snowc() -> None:
    """눈덮임 비율 = min(1, 눈 깊이(물당량) / 15 mm). 병합된 sd에서 만들어 data/merged/snowc.nc로 둔다."""
    out, src = C.DATA / "merged" / "snowc.nc", C.DATA / "merged" / "sd.nc"
    if out.exists():
        with xr.open_dataset(out) as a, xr.open_dataset(src) as b:
            if a.time.size == b.time.size and a.time.values[-1] == b.time.values[-1]:
                return
    sd = xr.open_dataarray(src).load()
    sc = (sd / C.SNOW_SWE_FULL).clip(0.0, 1.0).astype("float32").rename("snowc")
    sc.attrs.update(long_name="snow cover fraction", definition=f"min(1, snow_depth[m w.e.] / {C.SNOW_SWE_FULL})")
    atomic_to_netcdf(sc.to_dataset(), out)
    p = C.DATA / "clim" / "snowc.nc"      # 평년값 캐시는 정의가 바뀔 수 있어 새로 만든다
    if p.exists():
        p.unlink()


def _landfrac() -> xr.DataArray:
    lf = xr.open_dataarray(C.DATA / "static" / "landfrac_nh.nc").load()
    return lf.assign_coords(lat=np.round(lf.lat.values, 6), lon=np.round(lf.lon.values, 6))


def land_weights(da: xr.DataArray) -> xr.DataArray:
    """육지 비율 0.5 이상 격자에 육지 비율 가중, 나머지 0."""
    lf = _landfrac().reindex(lat=da.lat, lon=da.lon, method="nearest")
    return lf.where(lf >= C.LAND_MIN, 0.0)


# ------------------------------------------------------------------ 영역 지수
def _pdo_daily(sst: xr.DataArray) -> pd.Series:
    """PDO: 20°N 이북 북태평양 SST 편차(30°S~60°N 평균을 날마다 뺌)의 월평균 EOF1에 일별 편차를 투영한다.

    부호: 북태평양 중앙(35~45°N, 160°E~160°W)이 차가울 때 양(+). 평년 기간 월평균 PC의 표준편차로 나눈다.
    """
    anom = anomaly(sst, field_clim("sst").sel(lat=sst.lat))
    gm = area_mean(anom, (-30, 60, 0, 360))
    s, n, w, e = C.FORCING["pdo"]["region"]
    sub = (anom - gm).sel(lat=slice(s, n))
    sub = sub.isel(lon=lon_mask(sub.lon.values, w, e))
    wgt = np.sqrt(np.cos(np.deg2rad(sub.lat.values)))[:, None]
    X = (sub.values * wgt).reshape(sub.sizes["time"], -1)
    ok = np.isfinite(X).all(0)
    X = X[:, ok]
    t = pd.DatetimeIndex(sub.time.values)
    base = (t.year >= C.START_YEAR) & (t.year <= C.CLIM[1])
    mon = pd.DataFrame(X[base]).groupby([t[base].year, t[base].month]).mean().values
    mon = mon - mon.mean(0)
    eof = np.linalg.svd(mon, full_matrices=False)[2][0]
    la = np.repeat(sub.lat.values, sub.sizes["lon"])[ok]
    lo = np.tile(sub.lon.values, sub.sizes["lat"])[ok]
    central = (la >= 35) & (la <= 45) & (lo >= 160) & (lo <= 200)
    if eof[central].mean() > 0:
        eof = -eof
    pc = pd.Series(X @ eof, index=t)
    mpc = pc.groupby([t.year, t.month]).mean()
    sd = mpc[[(y, m) for (y, m) in mpc.index if C.CLIM[0] <= y <= C.CLIM[1]]].std()
    return (pc / sd).rename("pdo")


def daily_indices() -> pd.DataFrame:
    """일별 강제인자 지수(편차, 표시 단위). 월평균 전용 지수(지면온도)는 여기 없다."""
    ensure_snowc()
    out = {}
    for key, sp in C.FORCING.items():
        if sp.get("monthly"):
            continue
        if key == "pdo":
            out[key] = _pdo_daily(open_field("sst").sel(lat=slice(-30, 70)).load())
            continue
        da = open_field(sp["field"])          # 영역만 골라 읽는다 (전체를 메모리에 올리지 않는다)
        w = land_weights(da) if sp["surface"] == "land" else None
        raw = area_mean(da, sp["region"], w).load().to_series()
        out[key] = series_anom(raw) * sp["scale"]
        log.info("강제인자 %s: %s", key, sp["label"])
    df = pd.DataFrame(out)
    df.index.name = "date"
    return df


def monthly_skt() -> tuple[pd.Series | None, xr.DataArray | None]:
    """CDS 월평균 지면온도로 만든 유라시아 지면온도 지수(월 편차, °C)와 월 편차장."""
    if not CDS_MONTHLY.exists():
        log.warning("CDS 월평균 지면온도 파일이 없어 '유라시아 지면온도(월평균)'는 건너뛴다")
        return None, None
    skt = xr.open_dataset(CDS_MONTHLY)["skt"].load()
    base = skt.sel(time=slice(f"{C.CLIM[0]}", f"{C.CLIM[1]}"))
    clim = base.groupby("time.month").mean()
    an = (skt.groupby("time.month") - clim).drop_vars("month")
    sp = C.FORCING["eurasia_skt"]
    s = area_mean(an, sp["region"], land_weights(an)).to_series() * sp["scale"]
    s.index = pd.DatetimeIndex(s.index).to_period("M").to_timestamp()
    return s.rename("eurasia_skt"), an


# ------------------------------------------------------------------ 월평균, 추세 제거
def monthly_means(daily: pd.DataFrame, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """완결된 달만 남긴 월평균, 그리고 이번 달(진행 중) 평균 한 줄."""
    cur0 = end.to_period("M").to_timestamp()
    full = daily[:cur0 - pd.Timedelta(days=1)]
    m = full.resample("MS").mean()
    cnt = full.resample("MS").count()
    m = m.where(cnt.values >= cnt.index.days_in_month.values[:, None])      # 빠진 날이 있는 달은 쓰지 않는다
    cur = daily[cur0:end].mean().to_frame().T
    cur.index = [cur0]
    return m, cur


def detrend_monthly(s: pd.Series, last_year: int) -> pd.Series:
    """달마다 따로 구한 연도에 대한 선형 추세를 뺀다(추세는 last_year까지로 맞춘다)."""
    out = pd.Series(np.nan, index=s.index)
    for mo in range(1, 13):
        sel = s.index.month == mo
        x = s[sel]
        fit = x[(x.index.year <= last_year) & x.notna()]
        if len(fit) < 10:
            continue
        b, a = np.polyfit(fit.index.year, fit.values, 1)
        out[sel] = x.values - (a + b * x.index.year.values)
    return out


# ------------------------------------------------------------------ 시차 상관
def _neff_p(x: np.ndarray, y: np.ndarray, r: float) -> tuple[float, float]:
    """Bretherton et al. (1999) 유효 표본 수와 양측 p값 (해마다 한 값인 계열에 쓴다)."""
    n = len(x)
    r1x = np.corrcoef(x[:-1], x[1:])[0, 1]
    r1y = np.corrcoef(y[:-1], y[1:])[0, 1]
    rr = r1x * r1y
    ne = float(np.clip(n * (1 - rr) / (1 + rr), 3, n)) if np.isfinite(rr) else float(n)
    t = r * np.sqrt((ne - 2) / max(1e-9, 1 - r * r))
    return ne, float(2 * stats.t.sf(abs(t), ne - 2))


def _bh(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg q값."""
    p = np.asarray(p, float)
    q = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    pv = p[ok]
    o = np.argsort(pv)
    rk = pv[o] * len(pv) / (np.arange(len(pv)) + 1)
    rk = np.minimum.accumulate(rk[::-1])[::-1]
    tmp = np.empty_like(pv)
    tmp[o] = np.minimum(rk, 1)
    q[ok] = tmp
    return q


def lag_correlations(mx: pd.DataFrame, my: pd.DataFrame, target_month: int, last_year: int,
                     rng: np.random.Generator) -> pd.DataFrame:
    """mx(강제인자 월 편차, 추세 제거), my(대상 월 편차, 추세 제거)의 시차 상관.

    season "month": 대상 달이 target_month인 해만(해마다 한 표본). season "ext": 11~3월 묶음(겨울 단위 부트스트랩).
    """
    idx = pd.date_range(min(mx.index.min(), my.index.min()), max(mx.index.max(), my.index.max()), freq="MS")
    mx, my = mx.reindex(idx), my.reindex(idx)
    last = pd.Timestamp(last_year + 1, 4, 1)       # 묶음은 지난겨울(3월)까지
    rows = []
    for season in ("month", "ext"):
        months = (target_month,) if season == "month" else C.FORCING_SEASON
        sel = idx[np.isin(idx.month, months) & (idx < (pd.Timestamp(last_year + 1, 1, 1) if season == "month" else last))]
        grp = np.where(sel.month >= 7, sel.year, sel.year - 1) if season == "ext" else sel.year.values
        ug = np.unique(grp)
        rows_of = {g: np.flatnonzero(grp == g) for g in ug}
        boots = [np.concatenate([rows_of[g] for g in rng.choice(ug, len(ug))]) for _ in range(N_BOOT_CORR)]
        for f in mx.columns:
            for L in C.FORCING_LAGS:
                xs = mx[f].shift(L).reindex(sel).values
                for t in my.columns:
                    ys = my[t].reindex(sel).values
                    ok = np.isfinite(xs) & np.isfinite(ys)
                    if ok.sum() < 15:
                        continue
                    r = float(np.corrcoef(xs[ok], ys[ok])[0, 1])
                    rb = []
                    for b in boots:
                        xb, yb = xs[b], ys[b]
                        k = np.isfinite(xb) & np.isfinite(yb)
                        if k.sum() > 5 and xb[k].std() > 0 and yb[k].std() > 0:
                            rb.append(np.corrcoef(xb[k], yb[k])[0, 1])
                    rb = np.asarray(rb)
                    lo, hi = np.percentile(rb, [2.5, 97.5])
                    p_boot = float(max(2 * min((rb <= 0).mean(), (rb >= 0).mean()), 1 / len(rb)))
                    if season == "month":
                        ne, p = _neff_p(xs[ok], ys[ok], r)
                    else:
                        ne, p = float(len(np.unique(grp[ok]))), p_boot
                    rows.append(dict(season=season, forcing=f, target=t, lag=L, r=r, lo=float(lo), hi=float(hi), n=int(ok.sum()),
                                     n_eff=ne, p=p, p_boot=p_boot, verdict=N.ci_word(lo, hi)))
    df = pd.DataFrame(rows)
    df["q"] = np.nan
    for s in df.season.unique():
        m = df.season == s
        df.loc[m, "q"] = _bh(df.loc[m, "p"].values)
    df["fdr"] = df.q < 0.10
    return df


# ------------------------------------------------------------------ 기존 회귀에 강제인자 더하기
def _fit(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def _cv_r2(X, y) -> float:
    pred = np.empty_like(y)
    for i in range(len(y)):
        m = np.ones(len(y), bool)
        m[i] = False
        mu, sd = X[m].mean(0), X[m].std(0, ddof=1)
        b = _fit((X[m] - mu) / sd, y[m])
        pred[i] = b[0] + ((X[i] - mu) / sd) @ b[1:]
    return float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def regression_compare(mon_all: pd.DataFrame, cur: pd.Series, target_month: int, last_year: int,
                       rng: np.random.Generator) -> list[dict]:
    """대상 달(해마다 한 표본) 회귀: 기존 인자 vs 기존 인자 + 강제인자(1개월 앞).

    기존 인자는 config.DRIVERS와 같은 것을 월 단위로 옮겼다: 추세(연도), 우랄·극소용돌이·Niño3.4(같은 달),
    바렌츠-카라 해빙(1개월 앞, 일 단위 30일 시차에 해당). 원자료 편차(추세를 빼지 않음)를 쓰고 추세는 인자로 넣는다.
    """
    L = C.FORCING_REG_LAG
    base_f = [("ural", 0), ("pv", 0), ("nino34", 0), ("bk_ice", 1)]
    idx = mon_all.index
    years = np.arange(C.START_YEAR, last_year + 1)

    def col(name, lag, yrs):
        s = mon_all[name].shift(lag)
        return np.array([s.get(pd.Timestamp(y, target_month, 1), np.nan) for y in yrs])

    def cur_val(name, lag):
        if lag == 0:
            return float(cur[name])
        return float(mon_all[name].get(pd.Timestamp(last_year + 1, target_month, 1) - pd.DateOffset(months=lag), np.nan))

    out = []
    for tgt in ("korea_t", "ea_t", "korea_p", "ea_p"):
        y = col(tgt, 0, years)
        Xb = np.column_stack([years.astype(float)] + [col(n, l, years) for n, l in base_f])
        for f, sp in C.FORCING.items():
            if f in ("bk_ice", "nino34") or f not in mon_all:
                continue
            xf = col(f, L, years)
            ok = np.isfinite(y) & np.isfinite(Xb).all(1) & np.isfinite(xf)
            if ok.sum() < 20:
                continue
            X0, X1 = Xb[ok], np.column_stack([Xb[ok], xf[ok]])
            r0, r1 = _cv_r2(X0, y[ok]), _cv_r2(X1, y[ok])
            mu, sd = X1.mean(0), X1.std(0, ddof=1)
            b = _fit((X1 - mu) / sd, y[ok])
            bs = []
            n = int(ok.sum())
            for _ in range(C.N_BOOT):
                k = rng.integers(0, n, n)
                m2, s2 = X1[k].mean(0), X1[k].std(0, ddof=1)
                if (s2 == 0).any():
                    continue
                bs.append(_fit((X1[k] - m2) / s2, y[ok][k])[-1])
            lo, hi = np.percentile(bs, [5, 95])
            xf_now = cur_val(f, L)
            z_now = (xf_now - mu[-1]) / sd[-1]
            out.append(dict(target=tgt, forcing=f, lag=L, n=n, r2cv_base=r0, r2cv_with=r1, d_r2cv=r1 - r0,
                            coef=float(b[-1]), lo=float(lo), hi=float(hi), verdict=N.ci_word(lo, hi),
                            z_now=float(z_now), contribution=float(b[-1] * z_now) if np.isfinite(z_now) else None,
                            observed_now=float(cur[tgt]) if tgt in cur else None))
    return out


# ------------------------------------------------------------------ 현재 상태
def current_state(daily: pd.DataFrame, skt: pd.Series | None, end: pd.Timestamp) -> dict:
    e = end.date()
    pds = {"last7": last_n(e, 7), "last30": last_n(e, 30), "month": month_of(e), "pentad": pentad(*pentad_of(e))}
    out = {}
    for key in daily.columns:
        s = daily[key].dropna()
        row = {}
        for k, p in pds.items():
            hist = same_dates_other_years(s, p.start, p.eff_end(e))
            if len(hist) < 20 or hist.index[-1] != end.year:
                continue
            row[k] = dict(standing(hist, C.CLIM), start=str(p.start), end=str(p.eff_end(e)), n_days=p.n_days(e),
                          label=p.label)
        out[key] = row
    if skt is not None:
        s = skt.dropna()
        last = s.index[-1]
        hist = s[s.index.month == last.month]
        hist.index = hist.index.year
        out["eurasia_skt"] = {"latest_month": dict(standing(hist, C.CLIM), month=f"{last:%Y-%m}", label=f"{last.year}년 {last.month}월")}
    return out


# ------------------------------------------------------------------ 문장
def _word(key: str, z: float) -> str:
    sp = C.FORCING[key]
    if key == "pdo":
        return N.sigma_word(z, "양(+)의 위상", "음(−)의 위상")
    hi, lo = WORDS[sp["group"]]
    return N.sigma_word(z, hi, lo)


def state_sentence(key: str, row: dict) -> str | None:
    sp = C.FORCING[key]
    st = row.get("last30") or row.get("latest_month")
    if not st:
        return None
    when = "최근 30일" if "last30" in row else st["label"]
    unit = "" if sp["unit"] == "σ" else sp["unit"]
    nd = 2 if sp["unit"] in ("σ", "°C") else 1
    s = (f"{sp['label']}: {when} 편차 {N.num(st['value'], nd, ' ' + unit if unit else 'σ')} "
         f"({N.num(st['sigma'], 1, 'σ')}, {st['year0']}년 이후 같은 날짜 {st['n_years']}개 해 중 높은 순 {st['rank_high']}위) → "
         f"{_word(key, st['sigma'])}.")
    if "last7" in row:
        s += f" 최근 7일 {N.num(row['last7']['sigma'], 1, 'σ')}."
    return s


def lag_sentences(lc: pd.DataFrame, target_month: int) -> list[str]:
    out = []
    sub = lc[lc.season == "month"]
    for t, tl in C.FORCING_TARGETS.items():
        s = sub[(sub.target == t) & (sub.verdict == "유의함")].copy()
        s = s.reindex(s.r.abs().sort_values(ascending=False).index)
        n_all = int(((sub.target == t)).sum())
        if s.empty:
            out.append(f"{MONTH_KO[target_month]} {tl}: 강제인자 {n_all}개 조합(인자 x 시차 0~2개월) 모두 95% 구간이 0을 포함한다 → 유의하지 않음.")
            continue
        parts = [f"{C.FORCING[r.forcing]['label']}({'같은 달' if r.lag == 0 else f'{r.lag}개월 앞'}) r={r.r:+.2f} "
                 f"[{r.lo:+.2f}, {r.hi:+.2f}]{', FDR 통과' if r.fdr else ', FDR 미통과'}" for r in s.head(4).itertuples()]
        out.append(f"{MONTH_KO[target_month]} {tl}: 95% 구간이 0을 벗어난 조합 {len(s)}/{n_all}개 — " + "; ".join(parts) + ".")
    return out


def regression_sentences(reg: list[dict], target_month: int) -> list[str]:
    out = []
    for tgt, tl in (("korea_t", "한반도 기온"), ("ea_t", "동아시아 기온")):
        rows = [r for r in reg if r["target"] == tgt]
        if not rows:
            continue
        best = max(rows, key=lambda r: r["d_r2cv"])
        sig = [r for r in rows if r["verdict"] == "유의함"]
        s = (f"{MONTH_KO[target_month]} {tl} 회귀: 기존 인자만의 교차검증 R² {best['r2cv_base']:.2f}. 강제인자 하나(1개월 앞)를 더했을 때 "
             f"가장 크게 오른 것은 {C.FORCING[best['forcing']]['label']}({best['r2cv_base']:.2f} → {best['r2cv_with']:.2f}, "
             f"ΔR² {best['d_r2cv']:+.2f}).")
        if sig:
            s += " 계수 90% 구간이 0을 벗어난 강제인자: " + ", ".join(
                f"{C.FORCING[r['forcing']]['label']} (표준화 계수 {r['coef']:+.2f} [{r['lo']:+.2f}, {r['hi']:+.2f}], 이번 달 기여 "
                f"{N.num(r['contribution'], 2, '°C')})" for r in sig) + "."
        else:
            s += " 더한 강제인자의 계수는 모두 90% 구간이 0을 포함한다 → 유의하지 않음."
        out.append(s)
    return out


def implication_sentences(state: dict, lc: pd.DataFrame) -> list[str]:
    """지금 편차가 '다소' 이상인 강제인자 중, 과거 상관이 유의한 대상과 그 부호로 본 방향. 예측이 아니라 과거 관계의 방향이다."""
    out = []
    sub = lc[(lc.season == "month") & (lc.verdict == "유의함")]
    for key, row in state.items():
        st = row.get("last30") or row.get("latest_month")
        if not st or not np.isfinite(st["sigma"]) or abs(st["sigma"]) < C.SIGMA_WEAK:
            continue
        s = sub[(sub.forcing == key) & (sub.lag >= 1)]
        if s.empty:
            continue
        r = s.loc[s.r.abs().idxmax()]
        sign = np.sign(r.r * st["sigma"])
        tl = C.FORCING_TARGETS[r.target]
        out.append(f"{N.josa(C.FORCING[key]['label'], '은/는')} 지금 {N.num(st['sigma'], 1, 'σ')}이고, 과거에 {r.lag}개월 뒤 {N.josa(tl, '와/과')} r={r.r:+.2f}"
                   f"(95% {r.lo:+.2f}~{r.hi:+.2f}{', FDR 통과' if r.fdr else ', FDR 미통과'})였다. 선형 관계로만 보면 "
                   f"{tl}의 {'양(+)' if sign > 0 else '음(−)'} 편차 쪽이며, 설명 분산은 r² = {r.r ** 2:.2f}에 그친다.")
    return out


# ------------------------------------------------------------------ 지도용 편차장
def window_maps(end: pd.Timestamp, ndays: int = 30) -> dict[str, xr.DataArray]:
    """최근 ndays일 평균 편차장: 해수면온도, 해빙, 눈덮임, 토양수분(육지), 육지 2 m 기온."""
    from .common import window_anom
    start = end - pd.Timedelta(days=ndays - 1)
    out = {}
    for name, sc in (("sst", 1.0), ("ci", 100.0), ("snowc", 100.0), ("swvl1", 100.0), ("t2m", 1.0)):
        da = window_anom(name, start.date(), end.date()) * sc
        if name in ("snowc", "swvl1", "t2m"):
            lf = _landfrac().reindex(lat=da.lat, lon=da.lon, method="nearest")
            da = da.where(lf >= C.LAND_MIN)
        if name == "ci":
            clim_max = field_clim("ci").max("doy").reindex(lat=da.lat, lon=da.lon)
            da = da.where(clim_max.fillna(0) > 0.02)       # 평년에도 해빙이 없는 바다는 지운다
        if name == "snowc":
            cl = field_clim("snowc").max("doy").reindex(lat=da.lat, lon=da.lon)
            da = da.where(cl.fillna(0) > 0.02)
        out[name] = da.sel(lat=slice(0, 90)).rename(name)
    return out


# ------------------------------------------------------------------ 그림
def plot_maps(maps: dict, skt_an: xr.DataArray | None, end: pd.Timestamp) -> None:
    plt = setup_plot()
    import cartopy.crs as ccrs
    from .common import diverging_cmap
    proj, pc = ccrs.NorthPolarStereo(central_longitude=120), ccrs.PlateCarree()
    panels = [("sst", "해수면온도 편차 (°C)", 2.0), ("ci", "해빙 농도 편차 (%p)", 40.0), ("snowc", "눈덮임 비율 편차 (%p)", 60.0),
              ("swvl1", "토양수분(0~7 cm) 편차 (%p 체적)", 8.0), ("t2m", "육지 2 m 기온 편차 (°C)", 6.0)]
    if skt_an is not None:
        last = skt_an.time.values[-1]
        panels.append(("skt", f"지면온도 편차 {str(last)[:7]} 월평균 (°C, CDS)", 6.0))
        lf = _landfrac().reindex(lat=skt_an.lat, lon=skt_an.lon, method="nearest")
        maps = dict(maps, skt=skt_an.sel(time=last).where(lf >= C.LAND_MIN))
    fig = plt.figure(figsize=(13, 9))
    boxes = {"sst": ["pdo", "koe_sst", "kor_sea_sst"], "ci": ["bk_ice", "okhotsk_ice"], "snowc": ["eurasia_snow", "tibet_snow"],
             "swvl1": ["mongolia_sm"], "t2m": ["eurasia_t2m"], "skt": ["eurasia_skt"]}
    levels = lambda v: np.linspace(-v, v, 13)          # 12칸, 눈금은 4칸마다
    for i, (k, title, vmax) in enumerate(panels):
        ax = fig.add_subplot(2, 3, i + 1, projection=proj)
        ax.set_extent([-180, 180, 15, 90], pc)
        da = maps[k]
        da_c = da.sel(lat=slice(15, 90))
        from cartopy.util import add_cyclic_point
        z, lon = add_cyclic_point(da_c.values, coord=da_c.lon.values)
        cf = ax.contourf(lon, da_c.lat, z, levels=levels(vmax), cmap=diverging_cmap(), extend="both", transform=pc)
        ax.coastlines(linewidth=0.5, color="#474747")
        for b in boxes.get(k, []):
            s, n, w, e = C.FORCING[b]["region"]
            s = max(s, 15)
            lo_ = np.linspace(w, e, 40)
            ax.plot(np.r_[lo_, lo_[::-1], w], np.r_[[s] * 40, [n] * 40, s], color="#191919", lw=0.9, ls="--", transform=pc)
        ax.set_title(title, fontsize=10, loc="left")
        fig.colorbar(cf, ax=ax, orientation="horizontal", pad=0.04, shrink=0.8, aspect=30, ticks=np.linspace(-vmax, vmax, 5))
    start = end - pd.Timedelta(days=29)
    fig.suptitle(f"강제인자 편차장 · 최근 30일 ({start.date()} ~ {end.date()}), 지면온도만 최근 월평균 · 점선: 지수 영역",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig15_forcing_maps.png")


def plot_lagcorr(lc: pd.DataFrame, target_month: int) -> None:
    plt = setup_plot()
    from .common import diverging_cmap
    fkeys = [f for f in C.FORCING if f in set(lc.forcing)]
    tkeys = list(C.FORCING_TARGETS)
    fig, axes = plt.subplots(2, 1, figsize=(15, 10.5))
    for ax, season, ttl in ((axes[0], "month", f"대상 달 {target_month}월 (해마다 1개, 1979~지난해)"),
                            (axes[1], "ext", "대상 달 11~3월 묶음 (겨울 단위 부트스트랩)")):
        sub = lc[lc.season == season]
        M = np.full((len(fkeys), len(tkeys) * 3), np.nan)
        S = np.zeros_like(M, dtype=int)
        for r in sub.itertuples():
            i, j = fkeys.index(r.forcing), tkeys.index(r.target) * 3 + r.lag
            M[i, j] = r.r
            S[i, j] = 2 if r.fdr and r.verdict == "유의함" else (1 if r.verdict == "유의함" else 0)
        im = ax.imshow(M, cmap=diverging_cmap(), vmin=-0.6, vmax=0.6, aspect="auto")
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                if np.isfinite(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:+.2f}".replace("+0.", "+.").replace("-0.", "-."), ha="center", va="center", fontsize=7,
                            fontweight="bold" if S[i, j] else "normal", color="#191919" if S[i, j] else "#888888")
                    if S[i, j]:
                        ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False, lw=1.6 if S[i, j] == 2 else 0.9, ec="#191919"))
        ax.set_yticks(range(len(fkeys)), [C.FORCING[f]["label"] for f in fkeys], fontsize=8.5)
        ax.set_xticks(range(len(tkeys) * 3), [f"{L}" for _ in tkeys for L in C.FORCING_LAGS], fontsize=7.5)
        for k, t in enumerate(tkeys):
            ax.text(k * 3 + 1, -0.9, C.FORCING_TARGETS[t], ha="center", va="bottom", fontsize=8.5)
            if k:
                ax.axvline(k * 3 - 0.5, color="#ffffff", lw=3)
        ax.set_xlabel("강제인자가 앞서는 달 수", fontsize=9)
        ax.grid(False)
        ax.set_title(ttl, fontsize=10.5, loc="left", pad=30)
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.01, label="상관계수 r")
    fig.suptitle("강제인자와 동아시아 기온·강수, 북반구 순환의 시차 상관 (달별 선형 추세 제거) · 굵은 글씨+얇은 테: 95% 구간이 0을 벗어남, "
                 "굵은 테: FDR(q<0.10)도 통과", fontsize=10.5, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig16_forcing_lagcorr.png")


# ------------------------------------------------------------------ 실행
def run(end) -> dict:
    end = pd.Timestamp(end)
    rng = np.random.default_rng(C.SEED)
    daily = daily_indices()[:end]
    skt, skt_an = monthly_skt()
    df = load_indices()[:end]
    targets = df[list(C.FORCING_TARGETS)]
    last_year = end.year - 1
    target_month = end.month

    # 월평균 (완결된 달) + 이번 달(진행 중)
    mf, curf = monthly_means(daily, end)
    mt, curt = monthly_means(targets, end)
    base = df[["ural", "pv", "nino34", "bk_ice"]]
    mb, curb = monthly_means(base, end)
    if skt is not None:
        mf["eurasia_skt"] = skt.reindex(mf.index)
    # 지면온도 대용 근거: 월평균 육지 2 m 기온 지수와 CDS 지면온도 지수의 상관
    subst = None
    if skt is not None:
        a = pd.concat([mf["eurasia_t2m"], skt], axis=1).dropna()
        subst = dict(r=float(a.corr().iloc[0, 1]), n=int(len(a)), period=f"{a.index[0]:%Y-%m}~{a.index[-1]:%Y-%m}",
                     r_detrended=float(pd.concat([detrend_monthly(a.iloc[:, 0], last_year), detrend_monthly(a.iloc[:, 1], last_year)],
                                                 axis=1).corr().iloc[0, 1]))

    mx = mf.apply(lambda s: detrend_monthly(s, last_year))
    my = mt.apply(lambda s: detrend_monthly(s, last_year))
    lc = lag_correlations(mx, my, target_month, last_year, rng)
    mon_all = pd.concat([mf, mt, mb], axis=1)
    mon_all = mon_all.loc[:, ~mon_all.columns.duplicated()]
    cur = pd.concat([curf.iloc[0], curt.iloc[0], curb.iloc[0]])
    cur = cur[~cur.index.duplicated()]
    reg = regression_compare(mon_all, cur, target_month, last_year, rng)
    state = current_state(daily, skt, end)

    sentences = [x for k in C.FORCING if k in state for x in [state_sentence(k, state[k])] if x]
    sentences_lag = lag_sentences(lc, target_month)
    sentences_reg = regression_sentences(reg, target_month)
    sentences_imp = implication_sentences(state, lc)
    n_tests = int((lc.season == "month").sum())
    n_sig = int(((lc.season == "month") & (lc.verdict == "유의함")).sum())
    n_fdr = int(((lc.season == "month") & (lc.verdict == "유의함") & lc.fdr).sum())
    overview = (f"{target_month}월 대상 시차 상관 {n_tests}개 중 95% 구간이 0을 벗어난 것은 {n_sig}개({100 * n_sig / max(n_tests, 1):.0f}%)다. "
                f"아무 관계가 없어도 약 5%는 우연히 유의하게 나오므로, 다중검정 보정(FDR q<0.10)까지 통과한 {n_fdr}개를 더 믿을 만한 관계로 본다.")

    # 저장
    C.OUT.mkdir(exist_ok=True)
    daily.round(4).to_csv(C.OUT / "forcing_daily.csv")
    mf.round(4).to_csv(C.OUT / "forcing_monthly.csv")
    lc.round(4).to_csv(C.OUT / "forcing_lagcorr.csv", index=False)
    pd.DataFrame(reg).round(4).to_csv(C.OUT / "forcing_regression.csv", index=False)
    cur_rows = []
    for k, row in state.items():
        for per, st in row.items():
            cur_rows.append(dict(forcing=k, label=C.FORCING[k]["label"], unit=C.FORCING[k]["unit"], period=per, start=st.get("start"),
                                 end=st.get("end", st.get("month")), value=st["value"], sigma=st["sigma"],
                                 percentile=st["percentile"], rank_high=st["rank_high"], n_years=st["n_years"]))
    pd.DataFrame(cur_rows).round(4).to_csv(C.OUT / "forcing_current.csv", index=False)
    summary = dict(end=str(end.date()), target_month=target_month, last_year=last_year, lags=list(C.FORCING_LAGS),
                   season_months=list(C.FORCING_SEASON), n_boot=N_BOOT_CORR,
                   forcings={k: {kk: (list(v) if isinstance(v, tuple) else v) for kk, v in sp.items()} for k, sp in C.FORCING.items()},
                   targets=C.FORCING_TARGETS, current=state, lagcorr=lc.to_dict("records"), regression=reg,
                   substitute=subst, skt_available=skt is not None,
                   skt_last=str(skt.index[-1].date())[:7] if skt is not None else None,
                   snow_definition=f"눈덮임 비율 = min(1, 눈 깊이(물당량) / {C.SNOW_SWE_FULL * 1000:.0f} mm), 1.5° 일평균 눈 깊이에 적용",
                   sentences=dict(state=sentences, lag=sentences_lag, regression=sentences_reg, implication=sentences_imp,
                                  overview=overview),
                   counts=dict(n_tests=n_tests, n_sig=n_sig, n_fdr=n_fdr))
    (C.OUT / "forcing_summary.json").write_text(json.dumps(_clean(summary), ensure_ascii=False, indent=1))

    maps = window_maps(end)
    plot_maps(maps, skt_an, end)
    plot_lagcorr(lc, target_month)
    atomic_to_netcdf(xr.Dataset({k: v.astype("float32") for k, v in maps.items()}), C.DATA / "derived" / "forcing_maps.nc")
    if skt_an is not None:
        atomic_to_netcdf(skt_an.isel(time=-1).to_dataset(name="skt"), C.DATA / "derived" / "skt_latest.nc")
    log.info("강제인자 분석: %s", overview)
    return summary


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (pd.Timestamp, dt.date)):
        return str(x)[:10]
    return x
