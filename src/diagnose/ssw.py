"""최근 성층권 돌연승온(SSW) 사례 판정과 원인·영향 정리 ("2026년 11월 SSW" 절).

사용자 제보 날짜를 그대로 쓰지 않는다. 분석 끝 날짜에서 config.SSW_CASE_LOOKBACK일 앞까지를 자료로 훑어
- 주 승온: 10 hPa 60°N 동서평균 동서풍이 동풍(<0)으로 바뀜 (Charlton & Polvani 2007, indices.strat.detect_ssw)
- 부 승온: 동풍 역전은 없지만 극관(60~90°N) 10 hPa 기온이 7일 안에 config.MINOR_DT_7D K 이상 오르거나
  극-60°N 기온 경도가 역전(극 쪽이 더 따뜻)
- 소용돌이 형태: 발생 −5~+10일 사이 10 hPa 소용돌이 조각(면적 15% 이상)이 2개 이상인 날이 2일 이상이면 분리형,
  아니면 변위형 (indices.strat.vortex_geometry)
을 판정하고, 발생 전 전조(100 hPa 에디 열속, 파수 1·2, 우랄블로킹, 알류샨 저기압)와 발생 후 경과
(극관 고도 하향 전파, AO·시베리아 고기압·동아시아 제트·동아시아 기온·강수)를 날짜별 수치로 정리한다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from .. import narrative as N
from ..common import (BLUE, COOL, INK2, ORANGE, VIOLET, WARM, _doy366, detrend_by_month, diverging_cmap,
                      get_logger, savefig, series_clim, setup_plot)
from ..periods import same_dates_other_years, standing

log = get_logger("diagnose.ssw")

AFTER_KEYS = {"ao": ("북극진동(AO)", "σ"), "siberian_high": ("시베리아 고기압", "hPa"), "ea_jet": ("동아시아 제트(U200)", "m/s"),
              "eawm": ("겨울몬순 지수", "m/s"), "korea_t": ("한반도 기온", "°C"), "ea_t": ("동아시아 기온", "°C"),
              "nchina_t": ("중국 북부 기온", "°C"), "japan_t": ("일본 기온", "°C"), "mongolia_t": ("몽골·시베리아 남부 기온", "°C"),
              "korea_p": ("한반도 강수", "mm/일"), "ea_p": ("동아시아 강수", "mm/일")}


def day_sigma(anom: pd.Series, date: pd.Timestamp, half: int = 15) -> float:
    """평년 기간에서 같은 날짜 ±half일 편차의 표준편차."""
    base = anom[f"{C.CLIM[0]}":f"{C.CLIM[1]}"].dropna()
    d = _doy366(base.index)
    d0 = _doy366(pd.DatetimeIndex([date]))[0]
    dist = np.minimum(np.abs(d - d0), 366 - np.abs(d - d0))
    return float(base[dist <= half].std())


def _first(mask: pd.Series):
    m = mask[mask]
    return m.index[0] if len(m) else None


def find_case(df: pd.DataFrame, ssw: pd.DataFrame, end: pd.Timestamp) -> dict:
    """끝 날짜 앞 LOOKBACK일 안의 승온 사례를 찾는다. 주 승온을 먼저, 없으면 부 승온."""
    t0 = end - pd.Timedelta(days=C.SSW_CASE_LOOKBACK)
    win = df[t0:end]
    rise = df["t10_cap"] - df["t10_cap"].rolling(8).min()        # 7일 안의 상승 폭 (오늘 - 앞 7일 최저)
    out = dict(search_start=str(t0.date()), search_end=str(end.date()),
               u_min=float(win.u1060.min()), u_min_date=str(win.u1060.idxmin().date()),
               t10_rise_max=float(rise[t0:end].max()), t10_rise_max_date=str(rise[t0:end].idxmax().date()),
               grad_max=float(win.t10_grad.max()), grad_max_date=str(win.t10_grad.idxmax().date()))
    major = None
    if len(ssw):
        sd = pd.to_datetime(ssw.date)
        hit = ssw[(sd >= t0) & (sd <= end)]
        if len(hit):
            major = hit.iloc[-1]
    if major is not None:
        out.update(kind="major", onset=str(pd.Timestamp(major.date).date()), confirmed=bool(major.confirmed))
        return out
    cand = (rise[t0:end] >= C.MINOR_DT_7D) | (df.t10_grad[t0:end] > 0)
    first = _first(cand)
    if first is not None:
        out.update(kind="minor", onset=str(first.date()), confirmed=True)
    else:
        out.update(kind="none")
    return out


def classify_vortex(df: pd.DataFrame, d0: pd.Timestamp) -> dict:
    seg = df[d0 - pd.Timedelta(days=5):d0 + pd.Timedelta(days=10)]
    split_days = int((seg.vortex_pieces >= 2).sum())
    pre = df[d0 - pd.Timedelta(days=10):d0]
    ratio = float(pre.wave2.mean() / pre.wave1.mean())
    return dict(kind="분리형" if split_days >= 2 else "변위형", split_days=split_days, window_days=int(len(seg)),
                lat_min=float(seg.vortex_lat.min()), lat_min_date=str(seg.vortex_lat.idxmin().date()),
                lon_at_min=float(seg.vortex_lon[seg.vortex_lat.idxmin()]),
                area_min=float(seg.vortex_area.min()), area_clim=float(series_clim(df.vortex_area)[seg.index].mean()),
                wave1_pre=float(pre.wave1.mean()), wave2_pre=float(pre.wave2.mean()), wave2_over_wave1=ratio,
                max_frac2=float(seg.vortex_frac2.max()))


def precursors(df: pd.DataFrame, d0: pd.Timestamp, ub: pd.DataFrame) -> dict:
    out = {}
    for key, (a, b) in {"vt100_21": (-21, -1), "vt100_14": (-14, -1), "wave1_14": (-14, -1), "wave2_14": (-14, -1),
                        "ural_21": (-21, -1), "aleutian_21": (-21, -1), "siberian_high_21": (-21, -1)}.items():
        col = key.rsplit("_", 1)[0]
        s, e = d0 + pd.Timedelta(days=a), d0 + pd.Timedelta(days=b)
        st = standing(same_dates_other_years(df[col], s.date(), e.date()))
        out[key] = dict(start=str(s.date()), end=str(e.date()), **st)
    ubo = pd.to_datetime(ub.onset)
    near = ub[(ubo >= d0 - pd.Timedelta(days=30)) & (ubo <= d0)]
    out["ural_events"] = [dict(onset=str(r.onset), end=str(r.end), duration=int(r.duration), max_anom=float(r.max_anom),
                               lead_days=int((d0 - pd.Timestamp(r.onset)).days)) for r in near.itertuples()]
    out["blocked_days_30"] = int(df.blocked[d0 - pd.Timedelta(days=30):d0 - pd.Timedelta(days=1)].sum())
    return out


def downward(pch: xr.DataArray, d0: pd.Timestamp, end: pd.Timestamp, thr: float = 1.0) -> list[dict]:
    """층별로 발생 −30일 이후 5일 평균 극관 고도 편차가 처음 +thr σ 이상이 된 날 (그 전날은 thr 미만)."""
    rows = []
    sm = pch.rolling(time=5, center=True, min_periods=3).mean()
    for lev in C.PCAP_LEVELS:
        s = sm.sel(level=lev).to_series()[d0 - pd.Timedelta(days=30):end]
        up = (s >= thr) & (s.shift(1) < thr)
        first = _first(up)
        rows.append(dict(level=int(lev), first=str(first.date()) if first is not None else None,
                         lag=int((first - d0).days) if first is not None else None, max=float(s.max()),
                         max_date=str(s.idxmax().date())))
    return rows


def after_effects(df: pd.DataFrame, d0: pd.Timestamp, end: pd.Timestamp) -> dict:
    out = {}
    for k in AFTER_KEYS:
        if k not in df:
            continue
        pre = df[k][d0 - pd.Timedelta(days=14):d0 - pd.Timedelta(days=1)]
        post = df[k][d0:end]
        st = standing(same_dates_other_years(df[k], d0.date(), end.date()))
        out[k] = dict(pre=float(pre.mean()), post=float(post.mean()), change=float(post.mean() - pre.mean()),
                      post_sigma=st["sigma"], post_pct=st["percentile"])
    return out


def history(df: pd.DataFrame, ssw: pd.DataFrame, d0: pd.Timestamp, end: pd.Timestamp, rng) -> dict:
    """1979년 이후 이른 겨울(11~12월) 주 승온 사례의 발생 후 0~60일 합성과 이번 사례 경과."""
    from ..attribute.composites import lag_composite, window_stat
    sd = pd.to_datetime(ssw.date)
    early = ssw[sd.dt.month.isin([11, 12]) & (sd < d0 - pd.Timedelta(days=60))]
    dates = pd.to_datetime(early.date)
    lags = np.arange(-20, 61)
    hist_end = d0.year - 1
    out = dict(dates=[str(d.date()) for d in dates], n=int(len(dates)), lags=lags.tolist(), series={})
    elapsed = int((end - d0).days)
    for k in ("u1060", "ao", "korea_t", "ea_t", "nchina_t", "japan_t", "mongolia_t", "korea_p", "ea_p"):
        s = df[k]
        if k.endswith("_t"):
            s = detrend_by_month(s, hist_end)
        sm = s.rolling(5, center=True, min_periods=3).mean()
        comp = lag_composite(sm, dates, lags, rng) if len(dates) >= 2 else None
        cur = sm.reindex(d0 + pd.to_timedelta(lags, unit="D"))
        out["series"][k] = dict(mean=None if comp is None else comp["mean"].round(3).tolist(),
                                lo=None if comp is None else comp["lo"].round(3).tolist(),
                                hi=None if comp is None else comp["hi"].round(3).tolist(),
                                current=[None if not np.isfinite(v) else round(float(v), 3) for v in cur.values])
        if k.endswith("_t") and len(dates) >= 2:
            out.setdefault("windows", {})[k] = {
                "0_30": window_stat(s, dates, 0, 30, rng), "31_60": window_stat(s, dates, 31, 60, rng),
                f"0_{elapsed}": window_stat(s, dates, 0, max(elapsed, 0), rng),
                "current_0_elapsed": float(s[d0:end].mean())}
    out["elapsed"] = elapsed
    return out


def sentences(case: dict) -> list[str]:
    """판정 결과를 규칙대로 문장으로 바꾼다."""
    S = []
    if case["kind"] == "none":
        S.append(f"{case['search_start']}~{case['search_end']}에 주 승온(10 hPa 60°N 동풍 역전)도 부 승온 기준"
                 f"(극관 10 hPa 기온 7일 상승 ≥ {C.MINOR_DT_7D:.0f} K 또는 극-60°N 기온 경도 역전)도 충족한 날이 없다. "
                 f"이 기간 동서풍 최저 {case['u_min']:.1f} m/s({case['u_min_date']}), 7일 기온 상승 최대 "
                 f"{case['t10_rise_max']:.1f} K({case['t10_rise_max_date']}).")
        return S
    d = case["detail"]
    kind = "주 승온(동서풍 역전)" if case["kind"] == "major" else "부 승온(동서풍 역전 없음)"
    S.append(f"판정: {kind}. 발생일 {case['onset']}" + ("" if case["confirmed"] else
             " (서풍 10일 연속 복귀를 아직 확인하지 못해 최종승온 여부는 잠정)") +
             f". 10 hPa 60°N 동서평균 동서풍 최저 {d['u']['min']:.1f} m/s({d['u']['min_date']}), "
             f"동풍 일수 {d['u']['easterly_days']}일" +
             (f", 서풍 복귀 {d['u']['return_date']}." if d['u']['return_date'] else ", 끝 날짜까지 서풍 복귀 없음."))
    t = d["t10"]
    S.append(f"극관(60~90°N) 10 hPa 기온: 최대 편차 {t['anom_max']:+.1f} K({t['anom_max_date']}, {t['anom_sigma']:+.1f}σ), "
             f"7일 상승 최대 {t['rise7_max']:.1f} K. 극-60°N 기온 경도 최대 {t['grad_max']:+.1f} K"
             + (" (역전)." if t["grad_max"] > 0 else " (역전 없음)."))
    v = d["vortex"]
    S.append(f"소용돌이 형태: {v['kind']}. 발생 −5~+10일 {v['window_days']}일 중 조각 2개 이상인 날 {v['split_days']}일, "
             f"중심 위도 최저 {v['lat_min']:.1f}°N({v['lat_min_date']}, {v['lon_at_min']:.0f}°E), "
             f"발생 전 10일 파수2/파수1 진폭비 {v['wave2_over_wave1']:.2f}.")
    p = d["precursors"]
    hf = p["vt100_21"]
    S.append(f"전조: 발생 전 21일 100 hPa 에디 열속 평균 {hf['value']:.1f} K·m/s ({hf['sigma']:+.1f}σ, "
             f"{N.sigma_word(hf['sigma'])}, {hf['year0']}년 이후 {hf['n_years']}개 해 중 {hf['rank_high']}위). "
             f"우랄 Z500 편차 {p['ural_21']['value']:+.0f} m({p['ural_21']['sigma']:+.1f}σ), "
             f"알류샨 해면기압 편차 {p['aleutian_21']['value']:+.1f} hPa({p['aleutian_21']['sigma']:+.1f}σ), "
             f"발생 전 30일 우랄 블로킹일 {p['blocked_days_30']}일, 5일 이상 우랄블로킹 사건 {len(p['ural_events'])}건"
             + ("".join(f" ({e['onset']} 시작, {e['duration']}일, 발생 {e['lead_days']}일 전)" for e in p["ural_events"])) + ".")
    dw = [r for r in d["downward"] if r["level"] in (10, 100, 500, 1000)]
    S.append("하향 전파(5일 평균 극관 고도 편차가 처음 +1σ 이상): " + ", ".join(
        f"{r['level']} hPa " + (f"{r['first']}(발생 {r['lag']:+d}일)" if r["first"] else f"미도달(최대 {r['max']:+.1f}σ)")
        for r in dw) + ".")
    a = d["after"]
    S.append(f"발생 후 {d['elapsed']}일(끝 날짜까지) 평균: " + ", ".join(
        f"{AFTER_KEYS[k][0]} {a[k]['post']:+.2f} {AFTER_KEYS[k][1]}({N.sigma_word(a[k]['post_sigma'])})"
        for k in ("ao", "siberian_high", "korea_t", "ea_t") if k in a) + ".")
    h = d["history"]
    if h["n"] >= 2 and "windows" in h and "korea_t" in h["windows"]:
        w = h["windows"]["korea_t"]
        S.append(f"과거 이른 겨울(11~12월) 주 승온 {h['n']}건 합성: 한반도 기온(추세 제거) 발생 후 0~30일 "
                 f"{w['0_30']['mean']:+.2f}°C [{w['0_30']['lo']:+.2f}, {w['0_30']['hi']:+.2f}] ({N.ci_word(w['0_30']['lo'], w['0_30']['hi'])}), "
                 f"31~60일 {w['31_60']['mean']:+.2f}°C [{w['31_60']['lo']:+.2f}, {w['31_60']['hi']:+.2f}] "
                 f"({N.ci_word(w['31_60']['lo'], w['31_60']['hi'])}). 이번 사례 0~{d['elapsed']}일 {w['current_0_elapsed']:+.2f}°C.")
    S.append(f"주의: 지표 영향은 보통 발생 후 수 주~두 달에 걸쳐 나타난다. 지금은 발생 후 {d['elapsed']}일 자료만 있으므로 "
             "위 '발생 후' 값은 지금까지 관측된 것이고, 과거 합성은 가능성의 범위일 뿐 예측이 아니다.")
    return S


def analyze(df: pd.DataFrame, end, rng) -> dict:
    end = pd.Timestamp(end)
    try:
        ssw = pd.read_csv(C.OUT / "events_ssw.csv")
    except pd.errors.EmptyDataError:
        ssw = pd.DataFrame(columns=["date", "winter", "min_u", "confirmed"])
    ub = pd.read_csv(C.OUT / "events_ural_blocking.csv")
    case = find_case(df, ssw, end)
    if case["kind"] != "none":
        d0 = pd.Timestamp(case["onset"])
        seg = df.u1060[d0:end]
        east = seg < 0
        ret = (seg > 0).astype(int)
        run = ret.groupby((ret == 0).cumsum()).cumsum()
        ret_day = _first(run >= C.SSW_RETURN_DAYS)
        ret_first = None if ret_day is None else ret_day - pd.Timedelta(days=C.SSW_RETURN_DAYS - 1)
        an = df.t10_cap_anom[d0 - pd.Timedelta(days=10):min(end, d0 + pd.Timedelta(days=20))]
        rise = (df.t10_cap - df.t10_cap.rolling(8).min())[d0 - pd.Timedelta(days=10):d0 + pd.Timedelta(days=5)]
        pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc")
        case["detail"] = dict(
            u=dict(min=float(seg.min()), min_date=str(seg.idxmin().date()), easterly_days=int(east.sum()),
                   return_date=None if ret_first is None else str(ret_first.date()),
                   clim_at_onset=float(series_clim(df.u1060)[d0])),
            t10=dict(anom_max=float(an.max()), anom_max_date=str(an.idxmax().date()),
                     anom_sigma=float(an.max() / day_sigma(df.t10_cap_anom, an.idxmax())),
                     rise7_max=float(rise.max()), grad_max=float(df.t10_grad[d0 - pd.Timedelta(days=10):d0 + pd.Timedelta(days=10)].max())),
            vortex=classify_vortex(df, d0), precursors=precursors(df, d0, ub),
            downward=downward(pch, d0, end), after=after_effects(df, d0, end),
            history=history(df, ssw, d0, end, rng), elapsed=int((end - d0).days))
        case["title"] = f"{d0.year}년 {d0.month}월 성층권 돌연승온"
    else:
        case["title"] = "최근 성층권 돌연승온 판정"
    case["sentences"] = sentences(case)
    plot(df, case, end)
    (C.OUT / "ssw_case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2, default=float))
    log.info("SSW 판정: %s %s", case["kind"], case.get("onset"))
    return case


def plot(df: pd.DataFrame, case: dict, end: pd.Timestamp) -> None:
    plt = setup_plot()
    t0 = end - pd.Timedelta(days=120)
    d = df[t0:end]
    fig, axes = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    clim = series_clim(df.u1060)[t0:end]
    ax = axes[0]
    ax.plot(d.index, d.u1060, color=BLUE, lw=2, label="관측")
    ax.plot(d.index, clim, color=INK2, lw=1, ls="--", label="평년")
    ax.axhline(0, color="#c2c2c2", lw=1)
    ax.set_title("10 hPa 60°N 동서평균 동서풍 (m/s)", fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=2)
    ax = axes[1]
    ax.plot(d.index, d.t10_cap_anom, color=WARM, lw=2)
    ax.axhline(0, color="#c2c2c2", lw=1)
    ax.set_title("극관(60~90°N) 10 hPa 기온 편차 (K)", fontsize=10, loc="left")
    ax = axes[2]
    ax.bar(d.index, d.vt100_anom, width=0.9, color=np.where(d.vt100_anom >= 0, ORANGE, VIOLET))
    ax.axhline(0, color="#c2c2c2", lw=1)
    ax.set_title("100 hPa 에디 열속 편차 (45~75°N, K·m/s) · 양(+)은 상향 파동 활동이 강함", fontsize=10, loc="left")
    ax = axes[3]
    pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc").sel(time=slice(t0, end))
    cf = ax.contourf(pch.time.values, pch.level.values, pch.values.T, levels=np.arange(-3, 3.01, 0.5),
                     cmap=diverging_cmap(), extend="both")
    ax.set_yscale("log")
    ax.invert_yaxis()
    ax.set_yticks([10, 30, 100, 300, 1000], labels=["10", "30", "100", "300", "1000"])
    ax.grid(False)
    ax.set_title("극관(65°N 이북) 고도 표준화 편차 (σ) · 세로축 hPa", fontsize=10, loc="left")
    fig.colorbar(cf, ax=axes[3], orientation="horizontal", pad=0.12, shrink=0.6, aspect=40)
    if case["kind"] != "none":
        for a in axes:
            a.axvline(pd.Timestamp(case["onset"]), color="#191919", lw=1.2, ls=":")
    fig.suptitle(f"{case['title']} · 점선: 판정 발생일", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig12_ssw_case.png")
    if case["kind"] == "none" or case["detail"]["history"]["n"] < 2:
        return
    h = case["detail"]["history"]
    lags = np.array(h["lags"])
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    for ax, k, ttl in zip(axes, ("u1060", "ao", "korea_t"),
                          ("10 hPa 60°N 동서풍 (m/s)", "북극진동 (σ)", "한반도 기온 편차 (°C, 추세 제거)")):
        s = h["series"][k]
        ax.fill_between(lags, s["lo"], s["hi"], color=INK2, alpha=0.18, lw=0)
        ax.plot(lags, s["mean"], color=INK2, lw=1.6, label=f"과거 이른 겨울 SSW {h['n']}건 평균")
        cur = np.array([np.nan if v is None else v for v in s["current"]], dtype=float)
        ax.plot(lags, cur, color=COOL if k == "korea_t" else BLUE, lw=2.2, label="이번 사례")
        ax.axhline(0, color="#c2c2c2", lw=1)
        ax.axvline(0, color="#c2c2c2", lw=1, ls=":")
        ax.set_title(ttl + " · 5일 이동평균", fontsize=10, loc="left")
    axes[0].legend(frameon=False, fontsize=9, loc="lower left")
    axes[-1].set_xlabel("발생일 기준 시차 (일)")
    fig.suptitle("이번 사례와 과거 이른 겨울 주 승온 합성 · 띠: 부트스트랩 5~95%", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig13_ssw_history.png")
