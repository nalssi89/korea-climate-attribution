"""4단계: 인자별 영향 정량화 (시차 합성도, 다중회귀 기여도, 최근 겨울 사례)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import (BLUE, COOL, GREEN, INK2, ORANGE, VIOLET, WARM, detrend_by_month, diverging_cmap,
                      get_logger, load_indices, savefig, series_clim, setup_plot)

log = get_logger("attribute")


def _band(ax, comp: pd.DataFrame, color: str, label: str) -> None:
    ax.fill_between(comp.lag, comp.lo, comp.hi, color=color, alpha=0.18, lw=0)
    ax.plot(comp.lag, comp["mean"], color=color, lw=2, label=label)
    ax.axhline(0, color="#c2c2c2", lw=1)
    ax.axvline(0, color="#c2c2c2", lw=1, ls=":")


def run_composites(df: pd.DataFrame, rng) -> dict:
    from . import composites as cp
    plt = setup_plot()
    out = {}
    hist_end = df.index[-1].year - 1
    t_dt = detrend_by_month(df["korea_t"], hist_end)       # 합성도는 장기 추세를 뺀 기온으로
    p = df["korea_p"]

    # --- 우랄블로킹 (11~3월에 시작한 사건)
    ub = pd.read_csv(C.OUT / "events_ural_blocking.csv", parse_dates=["onset", "end"])
    ubw = ub[ub.onset.dt.month.isin(C.EXT_WINTER)]
    lags = np.arange(-10, 16)
    c_t, c_p = cp.lag_composite(t_dt, ubw.onset, lags, rng), cp.lag_composite(p, ubw.onset, lags, rng)
    c_u = cp.lag_composite(df["ural"], ubw.onset, lags, rng)
    c_sh = cp.lag_composite(df["siberian_high"], ubw.onset, lags, rng)
    fig, axes = plt.subplots(4, 1, figsize=(8, 10.5), sharex=True)
    for ax, c, col, ttl in zip(axes, (c_u, c_sh, c_t, c_p), (INK2, VIOLET, BLUE, GREEN),
                               ("우랄 Z500 편차 (m)", "시베리아 고기압 편차 (hPa)", "한반도 기온 편차 (°C, 추세 제거)",
                                "한반도 강수 편차 (mm/일)")):
        _band(ax, c, col, ttl)
        ax.set_title(ttl, fontsize=10, loc="left")
    axes[-1].set_xlabel("블로킹 시작일 기준 시차 (일)")
    fig.suptitle(f"우랄블로킹 시작일 합성도 · 11~3월 사건 {len(ubw)}건 · 띠: 부트스트랩 5~95%", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig06_ural_blocking_composite.png")
    kmin = c_t.loc[c_t["mean"].idxmin()]
    out["ural"] = dict(n_events=int(len(ubw)), n_all=int(len(ub)), mean_duration=float(ubw.duration.mean()),
                       t_min_lag=int(kmin.lag), t_min=float(kmin["mean"]), t_min_lo=float(kmin.lo), t_min_hi=float(kmin.hi),
                       t_lag_3_10=cp.window_stat(t_dt, ubw.onset, 3, 10, rng),
                       t_lag_m10_m1=cp.window_stat(t_dt, ubw.onset, -10, -1, rng),
                       p_lag_0_10=cp.window_stat(p, ubw.onset, 0, 10, rng),
                       sh_lag_0_7=cp.window_stat(df["siberian_high"], ubw.onset, 0, 7, rng))
    c_t.assign(var="korea_t").to_csv(C.OUT / "composite_ural_blocking.csv", index=False)

    # --- SSW
    ssw = pd.read_csv(C.OUT / "events_ssw.csv", parse_dates=["date"]) if (C.OUT / "events_ssw.csv").stat().st_size > 5 \
        else pd.DataFrame(columns=["date"])
    lags = np.arange(-20, 61)
    sm_t, sm_p = t_dt.rolling(5, center=True).mean(), p.rolling(5, center=True).mean()
    if len(ssw) >= 3:
        c_t, c_p = cp.lag_composite(sm_t, ssw.date, lags, rng), cp.lag_composite(sm_p, ssw.date, lags, rng)
        c_u = cp.lag_composite(df["u1060"], ssw.date, lags, rng)
        c_ao = cp.lag_composite(df["ao"].rolling(5, center=True).mean(), ssw.date, lags, rng)
        fig, axes = plt.subplots(4, 1, figsize=(8, 10.5), sharex=True)
        for ax, c, col, ttl in zip(axes, (c_u, c_ao, c_t, c_p), (INK2, VIOLET, BLUE, GREEN),
                                   ("10 hPa 60°N 동서풍 (m/s)", "북극진동 (σ, 5일 이동평균)",
                                    "한반도 기온 편차 (°C, 추세 제거, 5일 이동평균)", "한반도 강수 편차 (mm/일, 5일 이동평균)")):
            _band(ax, c, col, ttl)
            ax.set_title(ttl, fontsize=10, loc="left")
        axes[-1].set_xlabel("SSW 중심일 기준 시차 (일)")
        fig.suptitle(f"성층권 돌연승온 합성도 · {len(ssw)}건 · 띠: 부트스트랩 5~95%", fontsize=11, x=0.01, ha="left")
        fig.tight_layout()
        savefig(fig, "fig07_ssw_composite.png")
        out["ssw"] = dict(n_events=int(len(ssw)), first=str(ssw.date.min().date()), last=str(ssw.date.max().date()),
                          t_0_30=cp.window_stat(t_dt, ssw.date, 0, 30, rng), t_31_60=cp.window_stat(t_dt, ssw.date, 31, 60, rng),
                          t_0_60=cp.window_stat(t_dt, ssw.date, 0, 60, rng),
                          p_0_30=cp.window_stat(p, ssw.date, 0, 30, rng), p_31_60=cp.window_stat(p, ssw.date, 31, 60, rng),
                          ao_0_30=cp.window_stat(df["ao"], ssw.date, 0, 30, rng),
                          dates=[str(d.date()) for d in ssw.date])
        c_t.assign(var="korea_t").to_csv(C.OUT / "composite_ssw.csv", index=False)
    else:
        out["ssw"] = dict(n_events=int(len(ssw)))

    # --- 엔소 겨울 월별
    from ..indices import enso
    oni = pd.read_csv(C.OUT / "oni_monthly.csv", index_col=0, parse_dates=True)
    phases = enso.winter_phase(oni["oni"])
    pct = (df["korea_p_raw"].resample("MS").sum() / df["korea_p_clim"].resample("MS").sum() - 1) * 100
    mon = pd.DataFrame({"korea_t": t_dt.resample("MS").mean(), "korea_p_pct": pct})
    mon = mon[mon.index <= df.index[-1] - pd.offsets.MonthBegin(1)]
    em = cp.enso_monthly(mon, phases, rng)
    em.round(3).to_csv(C.OUT / "composite_enso_monthly.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    months, names = [11, 12, 1, 2, 3], ["11월", "12월", "1월", "2월", "3월"]
    for ax, var, ttl in zip(axes, ("korea_t", "korea_p_pct"), ("한반도 기온 편차 (°C, 추세 제거)", "한반도 강수 평년 대비 편차 (%)")):
        for k, (ph, col) in enumerate((("엘니뇨", ORANGE), ("라니냐", BLUE))):
            s = em[(em["var"] == var) & (em.phase == ph)].set_index("month").reindex(months)
            x = np.arange(5) + (k - 0.5) * 0.36
            ax.bar(x, s["mean"], width=0.32, color=col, label=f"{ph} 겨울 ({int(s.n.max())}회)")
            ax.errorbar(x, s["mean"], yerr=[s["mean"] - s.lo, s.hi - s["mean"]], fmt="none", ecolor="#191919", elinewidth=1, capsize=2)
        ax.axhline(0, color="#c2c2c2", lw=1)
        ax.set_xticks(np.arange(5), names)
        ax.set_title(ttl, fontsize=10, loc="left")
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle("엔소 겨울의 월별 한반도 기온·강수 · 막대: 평균, 선: 부트스트랩 5~95%", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig08_enso_monthly.png")
    out["enso"] = dict(n_el=int((phases.phase == "엘니뇨").sum()), n_la=int((phases.phase == "라니냐").sum()),
                       n_neutral=int((phases.phase == "중립").sum()),
                       table=json.loads(em.round(3).to_json(orient="records", force_ascii=False)))
    if "oni_noaa" in oni:
        both = oni.dropna(subset=["oni", "oni_noaa"])
        out["enso"]["noaa_check"] = dict(n=int(len(both)), corr=float(both.oni.corr(both.oni_noaa)),
                                         rmse=float(np.sqrt(((both.oni - both.oni_noaa) ** 2).mean())))
    return out


def run_regression(df: pd.DataFrame, end: pd.Timestamp, rng) -> dict:
    from . import regression as rg
    plt = setup_plot()
    tab = rg.window_table(df, end)
    res = {y: rg.attribute(tab, y, rng) for y in ("korea_t", "korea_p")}
    res["links"] = rg.links_table(tab)
    tab.to_csv(C.OUT / "regression_samples.csv", index=False, float_format="%.4f")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, y, unit, ttl in zip(axes, ("korea_t", "korea_p"), ("°C", "mm/일"), ("기온 편차", "강수 편차")):
        r = res[y]
        labels = [f["label"] for f in r["factors"]] + ["잔차(설명 안 됨)", "관측"]
        vals = [f["contribution"] for f in r["factors"]] + [r["residual"], r["observed"]]
        ypos = np.arange(len(vals))[::-1]
        cols = [WARM if v >= 0 else COOL for v in vals[:-2]] + ["#9c9c9c", "#191919"]
        ax.barh(ypos, vals, color=cols, height=0.6)
        for f, yy in zip(r["factors"], ypos):
            ax.plot([f["lo"], f["hi"]], [yy, yy], color="#191919", lw=1.2)
            if f["single"] is not None:
                ax.plot(f["single"], yy, marker="D", ms=5, color="white", mec="#191919", mew=1.1, ls="none")
        ax.axvline(0, color="#c2c2c2", lw=1)
        ax.set_yticks(ypos, labels)
        ax.set_xlabel(unit)
        ax.set_title(f"한반도 {ttl} 기여도 · 교차검증 R² = {r['r2_cv']:.2f}", fontsize=10.5, loc="left")
        ax.grid(axis="y", visible=False)
    fig.suptitle(f"{tab[tab.is_target].end.iloc[0].date()}까지 30일의 인자별 기여도 · 선: 부트스트랩 5~95%, ◇: 인자 하나만 넣은 회귀",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig09_attribution.png")

    mc = rg.monthly_coefficients(df, rng)
    mc.round(4).to_csv(C.OUT / "regression_monthly_coefficients.csv", index=False)
    periods = list(dict.fromkeys(mc.period))
    factors = list(C.DRIVERS)
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    for ax, y, unit in zip(axes, ("korea_t", "korea_p"), ("°C", "mm/일")):
        s = mc[mc.target == y]
        m = s.pivot(index="factor", columns="period", values="coef").loc[factors, periods]
        sig = ((s.lo > 0) | (s.hi < 0)).groupby([s.factor, s.period]).first().unstack().loc[factors, periods]
        vmax = float(np.abs(m.values).max())
        im = ax.imshow(m.values, cmap=diverging_cmap(), vmin=-vmax, vmax=vmax, aspect="auto")
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                ax.text(j, i, f"{m.values[i, j]:+.2f}" + ("*" if sig.values[i, j] else ""), ha="center", va="center",
                        fontsize=9, color="white" if abs(m.values[i, j]) > 0.6 * vmax else "#191919")
        ax.set_xticks(range(len(periods)), periods)
        ax.set_yticks(range(len(factors)), [rg.FACTOR_LABEL[f] for f in factors])
        ax.grid(False)
        r2 = s.groupby("period").r2.first().reindex(periods)
        ax.set_title(f"{'기온' if y == 'korea_t' else '강수'}: 인자 1σ당 변화 ({unit}) · R² " +
                     ", ".join(f"{v:.2f}" for v in r2), fontsize=9.5, loc="left")
        fig.colorbar(im, ax=ax, pad=0.02)
    fig.suptitle("달별·계절별 표준화 회귀계수 · *: 부트스트랩 5~95% 구간이 0을 포함하지 않음", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig10_monthly_coefficients.png")
    res["monthly"] = json.loads(mc.round(4).to_json(orient="records", force_ascii=False))
    return res


def run_cases(df: pd.DataFrame, end: pd.Timestamp) -> list[dict]:
    from . import cases
    plt = setup_plot()
    ub = pd.read_csv(C.OUT / "events_ural_blocking.csv")
    try:
        ssw = pd.read_csv(C.OUT / "events_ssw.csv")
    except pd.errors.EmptyDataError:
        ssw = pd.DataFrame()
    oni = pd.read_csv(C.OUT / "oni_monthly.csv", index_col=0, parse_dates=True)
    years = cases.recent_winters(end)
    out = [cases.winter_summary(df, y, ub, ssw, oni) for y in years]
    pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc")
    uclim = series_clim(df["u1060"])
    fig, axes = plt.subplots(4, len(years), figsize=(5.2 * len(years), 11.5), sharex="col", sharey="row",
                             layout="constrained")
    for j, (y, w) in enumerate(zip(years, out)):
        d = df[f"{y}-11-01":f"{y + 1}-03-31"]
        ax = axes[0, j]
        ax.bar(d.index, d.korea_t, width=1.0, color=np.where(d.korea_t >= 0, WARM, COOL))
        ax.set_title(f"{w['winter']} 겨울 · {w['enso']} (ONI {w['oni_djf']:+.1f})\n한반도 기온 편차 (°C)", fontsize=10, loc="left")
        ax = axes[1, j]
        ax.plot(d.index, d.ural, color=BLUE, lw=1.8)
        ax.fill_between(d.index, 0, 1, where=d.blocked.values.astype(bool), transform=ax.get_xaxis_transform(),
                        color=ORANGE, alpha=0.2, lw=0)
        ax.set_title("우랄 Z500 편차 (m) · 주황: 블로킹일", fontsize=10, loc="left")
        ax = axes[2, j]
        ax.plot(d.index, d.u1060, color=BLUE, lw=1.8, label="관측")
        ax.plot(d.index, uclim[d.index], color=INK2, lw=1, ls="--", label="평년")
        for e in w["events"]:
            if e["kind"] == "SSW":
                ax.axvline(pd.Timestamp(e["date"]), color="#191919", lw=1.2)
                ax.annotate("SSW", (pd.Timestamp(e["date"]), 0.92), xycoords=("data", "axes fraction"), fontsize=8,
                            ha="left", xytext=(3, 0), textcoords="offset points")
        ax.set_title("10 hPa 60°N 동서풍 (m/s)", fontsize=10, loc="left")
        if j == 0:
            ax.legend(frameon=False, fontsize=8, loc="lower left", ncol=2)
        ax = axes[3, j]
        p = pch.sel(time=slice(d.index[0], d.index[-1]))
        cf = ax.contourf(p.time.values, p.level.values, p.values.T, levels=np.arange(-3, 3.01, 0.5),
                         cmap=diverging_cmap(), extend="both")
        ax.set_yscale("log")
        ax.set_yticks([10, 30, 100, 300, 1000], labels=["10", "30", "100", "300", "1000"])
        ax.grid(False)
        ax.set_title("극관 고도 표준화 편차 (σ), 세로축 hPa", fontsize=10, loc="left")
        for a in axes[:3, j]:
            a.axhline(0, color="#c2c2c2", lw=0.8)
        ax.tick_params(axis="x", labelrotation=30)
    axes[3, 0].invert_yaxis()
    fig.colorbar(cf, ax=axes[3, :].tolist(), location="right", shrink=0.9, aspect=18, pad=0.01)
    savefig(fig, "fig11_recent_winters.png")
    return out


def run_periods(df: pd.DataFrame, end, rng) -> tuple[list[dict], list[dict]]:
    """반순·주·월·최근 7일·최근 30일 단위 진단과 기여도 (PLAN의 '분석 기간 단위')."""
    from .. import periods as P
    from . import periods as AP
    eng = AP.Engine(df)
    res = [AP.analyze_period(eng, p, end.date(), rng) for p in P.recent_periods(end.date())]
    r2 = AP.r2_by_kind(res)
    light = [{k: v for k, v in r.items() if k != "attribution"} | {"attribution": {
        k: v for k, v in r["attribution"].items() if k != "maps"}} for r in res]
    (C.OUT / "periods_summary.json").write_text(json.dumps(dict(end=str(end.date()), r2_by_kind=r2, periods=light),
                                                         ensure_ascii=False, indent=1, default=float))
    log.info("기간 단위 분석 %d개: %s", len(res), ", ".join(f"{r['kind_label']} R²cv(한반도 기온) {r['r2cv_korea_t']:.2f}" for r in r2))
    return res, r2


def run(end) -> dict:
    end = pd.Timestamp(end)
    df = load_indices()
    rng = np.random.default_rng(C.SEED)
    out = dict(end=str(end.date()), composites=run_composites(df, rng), regression=run_regression(df, end, rng),
               cases=run_cases(df, end))
    out["periods"], out["r2_by_kind"] = run_periods(df, end, rng)
    (C.OUT / "attribution.json").write_text(json.dumps({k: v for k, v in out.items() if k != "periods"},
                                                       ensure_ascii=False, indent=2, default=float))
    r = out["regression"]["korea_t"]
    log.info("기여도 완료: 관측 %+.2f°C = 설명 %+.2f + 잔차 %+.2f (교차검증 R² %.2f)", r["observed"], r["predicted"],
             r["residual"], r["r2_cv"])
    return out
