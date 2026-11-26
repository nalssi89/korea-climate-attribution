"""5단계: 한국어 요약 보고서(HTML 한 페이지). 문장과 표의 수치는 모두 앞 단계의 계산 결과에서 읽는다."""
from __future__ import annotations

import base64
import json

import pandas as pd

from .. import config as C
from ..attribute.regression import FACTOR_LABEL
from ..diagnose import INDEX_LABEL

CSS = """
:root{--bg:#f9f9f9;--card:#fff;--ink:#191919;--ink2:#666;--line:#e7e7e7;--warm:#dc3c3d;--cool:#257de0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:'Pretendard','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;line-height:1.65;font-size:16px}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.3;margin:8px 0 4px}h2{font-size:1.25rem;margin:40px 0 10px;padding-top:14px;border-top:1px solid var(--line)}
h3{font-size:1.02rem;margin:22px 0 6px}.sub{color:var(--ink2);margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .k{color:var(--ink2);font-size:.85rem}.tile .v{font-size:1.7rem;font-weight:700;line-height:1.25}
.tile .n{color:var(--ink2);font-size:.85rem}
.pos{color:var(--warm)}.neg{color:var(--cool)}
figure{margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
figure img{width:100%;height:auto;display:block}figcaption{color:var(--ink2);font-size:.88rem;padding:8px 4px 2px}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--ink2);font-weight:600;background:#fafafa}th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}ul{padding-left:1.2em}li{margin:4px 0}
.note{background:#fff8e6;border:1px solid #f1dfae;border-radius:10px;padding:12px 16px;margin:14px 0}
code{background:#efefef;border-radius:4px;padding:1px 5px;font-size:.88em}
"""


def _s(v: float, nd: int = 1, unit: str = "") -> str:
    """부호를 붙이고 색을 입힌 숫자."""
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    return f'<span class="{cls}">{v:+.{nd}f}{unit}</span>'


def _img(name: str, caption: str) -> str:
    p = C.REPORTS / "figures" / name
    if not p.exists():
        return f'<div class="note">그림 {name}이(가) 만들어지지 않았다.</div>'
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><img alt="{caption}" src="data:image/png;base64,{b64}"><figcaption>{caption}</figcaption></figure>'


def _table(head: list[str], rows: list[list[str]]) -> str:
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def _ci_word(lo: float, hi: float) -> str:
    return "신뢰구간이 0을 벗어남" if (lo > 0 or hi < 0) else "신뢰구간이 0을 포함"


def _rank(r: dict) -> str:
    return f"{r['n_years']}개 해 중 높은 순 {r['rank_high']}위"


def run():
    rec = json.loads((C.OUT / "recent_summary.json").read_text())
    att = json.loads((C.OUT / "attribution.json").read_text())
    status = json.loads((C.OUT / "fetch_status.json").read_text()) if (C.OUT / "fetch_status.json").exists() else {}
    val = pd.read_csv(C.OUT / "validation_overlap.csv") if (C.OUT / "validation_overlap.csv").exists() else None
    oni = pd.read_csv(C.OUT / "oni_monthly.csv", index_col=0, parse_dates=True)
    ssw_all = pd.read_csv(C.OUT / "events_ssw.csv") if (C.OUT / "events_ssw.csv").stat().st_size > 5 else pd.DataFrame()
    ub_all = pd.read_csv(C.OUT / "events_ural_blocking.csv")
    k, idx = rec["korea"], rec["indices"]
    rt, rp = att["regression"]["korea_t"], att["regression"]["korea_p"]
    comp = att["composites"]
    start, end = rec["start"], rec["end"]
    target_source = "ASOS 전국 평균" if "asos" in rec else "ERA5(육지 가중 평균)"
    H: list[str] = []

    # ------------------------------------------------------------ 머리말, 요약
    H.append(f"<h1>한반도 기온·강수 원인 규명 보고서</h1><p class='sub'>분석 기간 {start} ~ {end} (30일) · "
             f"평년 {C.CLIM[0]}~{C.CLIM[1]} · 과거 통계 {C.START_YEAR}~현재 · 한반도 값: ERA5 육지 가중 평균</p>")
    explained = rt["predicted"]
    H.append('<div class="tiles">'
             f'<div class="tile"><div class="k">한반도 평균기온 편차</div><div class="v">{_s(k["t_anom"], 2, "°C")}</div>'
             f'<div class="n">평균 {k["t_mean"]:.1f}°C · {_rank(idx["korea_t"])}</div></div>'
             f'<div class="tile"><div class="k">강수량 (평년비)</div><div class="v">{k["p_ratio"]:.0f}%</div>'
             f'<div class="n">{k["p_total"]:.1f} mm / 평년 {k["p_normal"]:.1f} mm</div></div>'
             f'<div class="tile"><div class="k">회귀로 설명된 기온 편차</div><div class="v">{_s(explained, 2, "°C")}</div>'
             f'<div class="n">잔차 {rt["residual"]:+.2f}°C · 교차검증 R² {rt["r2_cv"]:.2f}</div></div>'
             f'<div class="tile"><div class="k">강수 회귀의 설명력</div><div class="v">R² {rp["r2_cv"]:.2f}</div>'
             f'<div class="n">교차검증 기준 · 잔차 {rp["residual"]:+.2f} mm/일</div></div></div>')

    top = sorted(rt["factors"], key=lambda f: -abs(f["contribution"]))
    bul = [f"기온은 평년보다 {_s(k['t_anom'], 2, '°C')}였다 (같은 기간 {_rank(idx['korea_t'])}). "
           f"30일 중 평년보다 낮았던 날은 {k['cold_days']}일, 일별 편차 범위는 {k['t_anom_min']:+.1f}°C({k['t_anom_min_date']}) ~ "
           f"{k['t_anom_max']:+.1f}°C({k['t_anom_max_date']})였다.",
           f"강수량은 {k['p_total']:.1f} mm로 평년({k['p_normal']:.1f} mm)의 {k['p_ratio']:.0f}%였다.",
           "기온 편차에 대한 회귀 기여도는 " + ", ".join(
               f"{f['label']} {_s(f['contribution'], 2, '°C')}" for f in top) +
           f" 순이고, 설명되지 않은 잔차는 {_s(rt['residual'], 2, '°C')}이다 (회귀 잔차의 표준편차 {rt['resid_sd']:.2f}°C)."]
    u = idx["ural"]
    bul.append(f"우랄블로킹: 우랄 영역 Z500 편차 평균 {_s(u['mean'], 0, ' m')}(표준화 {u['z']:+.1f}σ), "
               f"30~90°E 블로킹일 {rec['blocked_days']}일.")
    n_ssw_win, ssw_note = 0, ""
    if len(ssw_all):
        sd = pd.to_datetime(ssw_all.date)
        near = ssw_all[(sd >= pd.Timestamp(start) - pd.Timedelta(days=60)) & (sd <= pd.Timestamp(end))]
        n_ssw_win = len(near)
        if n_ssw_win:
            ssw_note = " 중심일: " + ", ".join(
                f"{r['date']}" + ("" if r["confirmed"] else "(서풍 10일 복귀를 아직 확인하지 못한 잠정 판정)")
                for _, r in near.iterrows()) + ". 과거 합성도에서 SSW 뒤 0~60일의 반응은 대부분 분석 기간 뒤에 온다."
    bul.append(f"성층권: 10 hPa 60°N 동서풍 평균 {idx['u1060']['mean']:.1f} m/s (같은 날짜 평년 {rec['u1060_clim']:.1f} m/s, "
               f"편차 {_s(idx['pv']['mean'], 1, ' m/s')}, {idx['pv']['z']:+.1f}σ), 기간 최저 {rec['u1060_min']:.1f} m/s "
               f"({rec['u1060_min_date']}). 분석 기간과 그 앞 60일 사이에 탐지된 SSW는 {n_ssw_win}건이다.{ssw_note}")
    last_oni = oni["oni"].dropna()
    bul.append(f"엔소: Niño3.4 편차 30일 평균 {_s(idx['nino34']['mean'], 2, '°C')}, 가장 최근 3개월 평균(ONI 방식)은 "
               f"{last_oni.index[-1]:%Y-%m} 중심 {last_oni.iloc[-1]:+.2f}°C.")
    far = [f for f in rt["factors"] if f["factor"] != "trend" and abs(f["z"]) >= 2.5]
    if far:
        bul.append("표본 범위 주의: " + ", ".join(f"{f['label']}({f['z']:+.1f}σ)" for f in far) +
                   "의 이번 값은 과거 같은 계절 표본의 가장자리이거나 바깥이라, 선형 회귀를 그대로 늘려 쓴 기여도는 불확실성이 구간보다 클 수 있다.")
    H.append("<h2>1. 핵심 요약</h2><ul>" + "".join(f"<li>{b}</li>" for b in bul) + "</ul>")
    H.append('<div class="note">기여도는 과거 같은 계절의 통계 관계에 이번 기간의 지수값을 대입한 추정이다. '
             '인자끼리 얽혀 있어 인과를 깔끔하게 나누지 못하며, 구간과 범위를 함께 읽어야 한다 (7장 참고).</div>')

    # ------------------------------------------------------------ 자료와 방법
    H.append("<h2>2. 자료와 방법</h2>")
    H.append(_table(["자료", "경로", "기간", "쓰임"], [
        ["ERA5 일평균 1.5°", "WeatherBench2 (익명)", f"{C.START_YEAR}~{C.WB2_LAST_YEAR}", "평년값, 과거 통계"],
        ["ERA5 0.25° → 1.5° 상자 평균", "Google ARCO-ERA5 원시 파일 (익명)", f"{C.ARCO_FIRST} ~ {status.get('자료 끝 날짜', end)}",
         "최근 겨울, 최근 한 달"],
        ["10 hPa 동서풍, 10·30 hPa 고도", "WeatherBench2 37층 / ARCO-ERA5", "전 기간", "SSW, 극관 고도"],
        ["ECMWF ARCO Zarr", "인증 필요", "-", status.get("ECMWF ARCO", "쓰지 않음")],
        ["기상청 ASOS 일자료", "API 허브 (인증 필요)", "-", status.get("KMA ASOS", "쓰지 않음")],
        ["NOAA 공식 ONI", "CPC", "-", status.get("NOAA ONI", "쓰지 않음")]]))
    H.append("<ul>"
             "<li>기압면 장과 해면기압은 2023년부터 00/06/12/18 UTC 평균, 기온·강수는 24시각 평균·합이다. "
             "그 앞은 WeatherBench2의 24시각 일평균이다. 날짜 경계는 UTC다.</li>"
             f"<li>한반도 값은 {C.REGIONS['korea'][0]}~{C.REGIONS['korea'][1]}°N, {C.REGIONS['korea'][2]}~{C.REGIONS['korea'][3]}°E의 "
             "1.5° 격자 9개를 육지 비율로 가중 평균한 ERA5 값이다.</li>"
             "<li>우랄블로킹: 30~90°E에서 Z500 남북 경도 역전(Tibaldi-Molteni 방식, 기준 위도 40.5/60/79.5°N ±4.5°)이 "
             f"연속 {C.BLOCK_MIN_LON:.0f}° 이상인 날을 블로킹일로, {C.BLOCK_MIN_DAYS}일 이상 이어지면 사건으로 본다. "
             "세기는 50~70°N, 40~80°E 평균 Z500 편차다.</li>"
             "<li>SSW: 11~3월에 10 hPa 60°N 동서평균풍이 동풍으로 바뀐 첫 날(Charlton-Polvani 기준, 사건 간 서풍 20일, 최종승온 제외).</li>"
             "<li>엔소: Niño3.4(5°S~5°N, 170~120°W) ERA5 해수면온도 편차와 그 3개월 이동평균. 겨울 위상은 DJF 평균 ±0.5°C 기준.</li>"
             "<li>연결 고리 인자: AO(20°N 이북 해면기압 제1 EOF), 시베리아 고기압(40~60°N, 80~120°E 해면기압), "
             "동아시아 제트(U200, 30~35°N, 130~160°E), 겨울몬순 지수(Jhun-Lee, U300 남북 차), "
             "필리핀해 고기압(10~30°N, 120~150°E 해면기압), 바렌츠-카라 해빙(65~85°N, 30~90°E).</li>"
             "<li>MJO 위상은 이번 구현에 넣지 않았다.</li></ul>")

    # ------------------------------------------------------------ 진단
    H.append("<h2>3. 최근 한 달 진단</h2>")
    H.append(_img("fig01_anomaly_maps.png", f"그림 1. {start} ~ {end} 평균 편차장."))
    rows = []
    for key in ["ural", "pv", "pch10", "pch500", "nino34", "ao", "siberian_high", "ea_jet", "eawm", "phil_sea", "bk_ice"]:
        r, (lab, unit) = idx[key], INDEX_LABEL[key]
        nd = 3 if key == "bk_ice" else 2
        rows.append([f"{lab} ({unit})", f"{r['mean']:+.{nd}f}", f"{r['z']:+.2f}", _rank(r)])
    H.append(_table(["지수 (30일 평균)", "값", "표준화(σ)", "같은 기간 순위"], rows))
    H.append("<p class='sub'>표준화는 평년 기간 같은 날짜 30일 평균의 표준편차 기준이다.</p>")
    H.append(_img("fig02_daily_series.png", "그림 2. 최근 90일의 한반도 기온·강수와 주요 지수 일별 시계열."))
    H.append(_img("fig03_wave_activity_flux.png", "그림 3. 250 hPa 고도 편차(색)와 Takaya-Nakamura 파동활동 플럭스(화살표). "
                  "화살표는 정상 로스비파 에너지가 퍼지는 방향이다."))
    ll = rec["korea_low_level"]
    H.append(_img("fig04_low_level.png", "그림 4. 850 hPa 온도 이류 편차와 수증기 수송 편차. 고원 지대의 850 hPa 값은 지면 아래 외삽값이다."))
    H.append(f"<p>한반도 상자 평균 850 hPa 수평 온도 이류는 {ll['adv']:+.2f} K/일, 평년 대비 편차는 {_s(ll['adv_anom'], 2, ' K/일')}였다. "
             f"850 hPa 바람 편차는 동서 {ll['u_anom']:+.1f}, 남북 {ll['v_anom']:+.1f} m/s, "
             f"수증기 수송 편차는 동서 {ll['qu_anom']:+.1f}, 남북 {ll['qv_anom']:+.1f} g/kg·m/s, 비습 편차는 {ll['q_anom']:+.2f} g/kg였다.</p>")
    H.append(_img("fig05_polar_cap_height.png", "그림 5. 최근 150일의 극관 평균 고도 표준화 편차 (연직-시간 단면)."))

    # ------------------------------------------------------------ 과거 영향
    H.append("<h2>4. 인자별 과거 영향 (시차 합성도)</h2>")
    cu = comp["ural"]
    H.append(f"<h3>우랄블로킹</h3><p>{C.START_YEAR}년 이후 탐지된 사건은 {cu['n_all']}건, 그중 11~3월에 시작한 {cu['n_events']}건"
             f"(평균 지속 {cu['mean_duration']:.1f}일)을 합성했다. 한반도 기온 편차(추세 제거)는 시작 후 {cu['t_min_lag']}일에 "
             f"가장 낮아 {cu['t_min']:+.2f}°C(5~95% 구간 {cu['t_min_lo']:+.2f} ~ {cu['t_min_hi']:+.2f})였다. "
             f"시작 후 3~10일 평균은 {cu['t_lag_3_10']['mean']:+.2f}°C({cu['t_lag_3_10']['lo']:+.2f} ~ {cu['t_lag_3_10']['hi']:+.2f}), "
             f"이 구간이 평년보다 낮았던 사건은 {cu['t_lag_3_10']['frac_neg'] * 100:.0f}%다. "
             f"시작 전 10일 평균은 {cu['t_lag_m10_m1']['mean']:+.2f}°C였다. "
             f"시베리아 고기압은 시작 후 0~7일 평균 {cu['sh_lag_0_7']['mean']:+.1f} hPa"
             f"({cu['sh_lag_0_7']['lo']:+.1f} ~ {cu['sh_lag_0_7']['hi']:+.1f}), "
             f"강수는 0~10일 평균 {cu['p_lag_0_10']['mean']:+.2f} mm/일({cu['p_lag_0_10']['lo']:+.2f} ~ {cu['p_lag_0_10']['hi']:+.2f})였다.</p>")
    H.append(_img("fig06_ural_blocking_composite.png", "그림 6. 우랄블로킹 시작일 기준 −10~+15일 합성도."))
    cs = comp["ssw"]
    H.append("<h3>성층권 돌연승온</h3>")
    if cs["n_events"] >= 3:
        H.append(f"<p>탐지된 SSW는 {cs['n_events']}건({cs['first']} ~ {cs['last']})이다. 한반도 기온 편차(추세 제거)는 중심일 후 0~30일 평균 "
                 f"{cs['t_0_30']['mean']:+.2f}°C({cs['t_0_30']['lo']:+.2f} ~ {cs['t_0_30']['hi']:+.2f}, {_ci_word(cs['t_0_30']['lo'], cs['t_0_30']['hi'])}), "
                 f"31~60일 평균 {cs['t_31_60']['mean']:+.2f}°C({cs['t_31_60']['lo']:+.2f} ~ {cs['t_31_60']['hi']:+.2f}, "
                 f"{_ci_word(cs['t_31_60']['lo'], cs['t_31_60']['hi'])})였다. 0~30일이 평년보다 낮았던 사건은 "
                 f"{cs['t_0_30']['frac_neg'] * 100:.0f}%다. 강수 편차는 0~30일 {cs['p_0_30']['mean']:+.2f}, 31~60일 "
                 f"{cs['p_31_60']['mean']:+.2f} mm/일, AO는 0~30일 평균 {cs['ao_0_30']['mean']:+.2f}σ"
                 f"({cs['ao_0_30']['lo']:+.2f} ~ {cs['ao_0_30']['hi']:+.2f})였다.</p>")
        H.append("<p class='sub'>탐지된 중심일: " + ", ".join(cs["dates"]) + "</p>")
        H.append(_img("fig07_ssw_composite.png", "그림 7. SSW 중심일 기준 −20~+60일 합성도."))
    else:
        H.append(f"<p>탐지된 SSW가 {cs['n_events']}건뿐이라 합성도를 만들지 않았다.</p>")
    ce = comp["enso"]
    H.append(f"<h3>엔소</h3><p>DJF 기준 엘니뇨 겨울 {ce['n_el']}회, 라니냐 겨울 {ce['n_la']}회, 중립 {ce['n_neutral']}회다.</p>")
    em = pd.DataFrame(ce["table"])
    rows = []
    for m, nm in zip((11, 12, 1, 2, 3), ("11월", "12월", "1월", "2월", "3월")):
        r = [nm]
        for var, nd in (("korea_t", 2), ("korea_p_pct", 0)):
            for ph in ("엘니뇨", "라니냐"):
                s = em[(em.month == m) & (em["var"] == var) & (em.phase == ph)]
                r.append(f"{s['mean'].iloc[0]:+.{nd}f} ({s.lo.iloc[0]:+.{nd}f} ~ {s.hi.iloc[0]:+.{nd}f})" if len(s) else "-")
        rows.append(r)
    H.append(_table(["달", "기온 °C: 엘니뇨", "기온 °C: 라니냐", "강수 %: 엘니뇨", "강수 %: 라니냐"], rows))
    H.append(_img("fig08_enso_monthly.png", "그림 8. 엘니뇨·라니냐 겨울의 월별 한반도 기온·강수 편차."))
    if "noaa_check" in ce:
        nc = ce["noaa_check"]
        H.append(f"<p>자체 계산한 ONI와 NOAA 공식 ONI의 상관은 {nc['corr']:.3f}, RMSE는 {nc['rmse']:.2f}°C다 ({nc['n']}개월).</p>")
    else:
        H.append("<p class='sub'>NOAA 공식 ONI와의 교차 확인은 하지 못했다 (cpc.ncep.noaa.gov에 닿지 않음).</p>")

    # ------------------------------------------------------------ 기여도
    H.append("<h2>5. 이번 달 인자별 기여도 (다중회귀)</h2>")
    H.append(f"<p>표본은 {rt['n_years']}개 해의 같은 계절 30일 창 {rt['n_samples']}개(분석 기간과 같은 날짜, ±15일, ±30일)이고, "
             "분석 대상 해는 학습에서 뺐다. 예측인자는 표준화했고 시차는 표에 적었다. "
             "신뢰구간은 해 단위 부트스트랩 5~95%다. '단독'은 추세와 그 인자만 넣은 회귀의 기여도다.</p>")
    for r, unit, nm in ((rt, "°C", "기온"), (rp, "mm/일", "강수")):
        rows = [[f["label"], f"{f['lag_days']}일", f"{f['z']:+.2f}", f"{f['coef']:+.2f} ({f['coef_lo']:+.2f} ~ {f['coef_hi']:+.2f})",
                 _s(f["contribution"], 2), f"{f['lo']:+.2f} ~ {f['hi']:+.2f}",
                 "-" if f["single"] is None else f"{f['single']:+.2f}", f"{f['range_lo']:+.2f} ~ {f['range_hi']:+.2f}"]
                for f in r["factors"]]
        rows.append(["합계(설명)", "", "", "", _s(r["predicted"], 2), "", "", ""])
        rows.append(["잔차", "", "", "", _s(r["residual"], 2), "", "", ""])
        rows.append(["관측", "", "", "", _s(r["observed"], 2), "", "", ""])
        H.append(f"<h3>{nm} ({unit}) · R² {r['r2']:.2f}, 교차검증 R² {r['r2_cv']:.2f}, 추세만 넣으면 {r['r2_trend_only']:.2f}</h3>")
        H.append(_table(["인자", "시차", "이번 값(σ)", "계수/1σ (구간)", "기여도", "5~95% 구간", "단독", "범위"], rows))
    H.append(_img("fig09_attribution.png", "그림 9. 인자별 기여도와 잔차. 장기 추세에는 회귀 절편을 합쳤다."))
    dc = pd.DataFrame(rt["driver_corr"])
    fac = list(C.DRIVERS)
    H.append("<h3>인자 사이의 상관 (같은 표본)</h3>")
    H.append(_table([""] + [FACTOR_LABEL[f] for f in fac],
                    [[FACTOR_LABEL[a]] + [f"{dc.loc[a, b]:+.2f}" for b in fac] for a in fac]))
    H.append("<h3>연결 고리 인자</h3>")
    H.append(_table(["지수", "이번 값(σ)", "기온과 상관", "강수와 상관", "우랄과", "극소용돌이와", "Niño3.4와"],
                    [[INDEX_LABEL[l["index"]][0], f"{l['z']:+.2f}", f"{l['corr_t']:+.2f}", f"{l['corr_p']:+.2f}",
                      f"{l['corr_ural']:+.2f}", f"{l['corr_pv']:+.2f}", f"{l['corr_nino34']:+.2f}"]
                     for l in att["regression"]["links"]]))
    H.append("<p class='sub'>연결 고리 인자는 원인 인자의 영향이 한반도로 전달되는 경로라서 회귀의 예측인자로 넣지 않고 상관만 본다.</p>")
    H.append(_img("fig10_monthly_coefficients.png", "그림 10. 달별·겨울철 표준화 회귀계수."))

    # ------------------------------------------------------------ 사례
    H.append(f"<h2>6. 최근 {len(att['cases'])}개 겨울 사례</h2>")
    H.append(_table(["겨울", "엔소 (DJF ONI)", "DJF 기온 편차", "DJF 강수 평년비", "DJF AO", "DJF 우랄 Z500",
                     "블로킹일(11~3월)", "U10 최저 (날짜)"],
                    [[w["winter"], f"{w['enso']} ({w['oni_djf']:+.2f})", _s(w["t_anom_djf"], 2, "°C"), f"{w['p_ratio_djf']:.0f}%",
                      f"{w['ao_djf']:+.2f}σ", f"{w['ural_djf']:+.0f} m", f"{w['blocked_days']}일",
                      f"{w['u1060_min']:.1f} m/s ({w['u1060_min_date']})"] for w in att["cases"]]))
    H.append(_img("fig11_recent_winters.png", "그림 11. 최근 겨울의 한반도 기온, 우랄 Z500, 성층권 바람, 극관 고도 단면."))
    for w in att["cases"]:
        H.append(f"<h3>{w['winter']} 겨울 ({w['enso']})</h3>")
        H.append(_table(["달", "기온 편차", "강수 평년비", "우랄 Z500", "블로킹일", "U10 60°N", "AO", "시베리아 고기압", "Niño3.4"],
                        [[m["month"], _s(m["t_anom"], 2, "°C"), f"{m['p_ratio']:.0f}%", f"{m['ural']:+.0f} m", f"{m['blocked_days']}",
                          f"{m['u1060']:.1f} m/s", f"{m['ao']:+.2f}", f"{m['siberian_high']:+.1f} hPa", f"{m['nino34']:+.2f}"]
                         for m in w["months"]]))
        ev = []
        for e in w["events"]:
            if e["kind"] == "우랄블로킹":
                ev.append(f"<li>{e['date']} 우랄블로킹 시작 ({e['end']}까지 {e['duration']}일, 최대 편차 {e['max_anom']:+.0f} m). "
                          f"시작 후 3~12일 한반도 기온 편차 평균 {_s(e['korea_t_after'], 2, '°C')}, 최저 {e['korea_t_min']:+.1f}°C.</li>")
            else:
                ev.append(f"<li>{e['date']} SSW 중심일 (동풍 최저 {e['min_u']:.1f} m/s). 한반도 기온 편차는 0~30일 "
                          f"{_s(e['korea_t_0_30'], 2, '°C')}, 31~60일 {_s(e['korea_t_31_60'], 2, '°C')}.</li>")
        H.append("<ul>" + ("".join(ev) if ev else "<li>이 겨울에는 5일 이상 이어진 우랄블로킹이나 SSW가 탐지되지 않았다.</li>") + "</ul>")

    # ------------------------------------------------------------ 한계
    H.append("<h2>7. 한계</h2><ul>"
             "<li><b>인자 간 얽힘</b>: 우랄블로킹, 바렌츠-카라 해빙, 성층권 극소용돌이, AO는 서로 영향을 주고받는다. "
             "5장의 '범위'(다중회귀와 단독 회귀의 차이)와 인자 사이 상관 표가 그 정도를 보여 준다. 기여도는 한 값이 아니라 범위로 읽어야 한다.</li>"
             f"<li><b>강수의 낮은 설명력</b>: 강수 회귀의 교차검증 R²는 {rp['r2_cv']:.2f}로, 대규모 인자로 설명되는 비율이 낮다. "
             "강수 편차의 대부분은 잔차(개별 저기압, 대기의 강 등 종관 규모 현상)에 남는다.</li>"
             f"<li><b>SSW 표본 수</b>: {C.START_YEAR}년 이후 탐지된 SSW는 {cs['n_events']}건뿐이라 합성도의 구간이 넓다. "
             "늦가을에는 SSW가 드물어 최근 한 달의 성층권은 극소용돌이 세기(10 hPa 60°N 동서풍 편차)로 평가했다.</li>"
             "<li><b>한 달은 표본 하나</b>: 회귀 잔차의 표준편차만큼은 내부 변동으로 언제든 생길 수 있다. "
             "회귀는 선형이고 시차를 미리 정해 두었으며, 사건의 강도·위치 차이는 반영하지 못한다.</li>"
             "<li><b>자료</b>: 한반도 값은 1.5° ERA5 격자 평균이라 관측소 평균과 다를 수 있다. "
             f"{C.ARCO_FIRST} 이후 대규모장은 하루 4시각 평균이고, 최근 약 3개월은 ERA5T(잠정) 자료다. "
             "엔소 지수는 ERA5 해수면온도와 고정 평년(1991~2020)을 써서 NOAA 공식 ONI와 다를 수 있다.</li></ul>")

    # ------------------------------------------------------------ 실행 상태
    H.append("<h2>8. 실행 상태와 자료 검증</h2>")
    if status:
        H.append(_table(["항목", "상태"], [[a, b] for a, b in status.items()]))
    if "asos" in rec:
        a = rec["asos"]
        H.append(f"<p>ASOS 전국 평균과 ERA5 한반도 평균의 일별 편차 상관은 기온 {a['corr_t']:.2f}, 강수 {a['corr_p']:.2f}다. "
                 f"분석 기간 ASOS 기온 편차는 {a['t_anom']:+.2f}°C다.</p>")
    else:
        H.append("<p>기상청 ASOS 자료를 받지 못해 관측 기준값과 ERA5의 비교 검증은 하지 못했다. 이 보고서의 한반도 값은 모두 ERA5다.</p>")
    if val is not None:
        H.append(f"<h3>자료 이음매 검증 ({C.ARCO_FIRST} ~ {C.WB2_OVERLAP_END}, WeatherBench2 대 ARCO-ERA5)</h3>")
        H.append(_table(["변수", "일수", "평균 차", "RMSE", "WB2 공간 표준편차", "상관"],
                        [[r["field"], str(r["n_day"]), f"{r['bias']:+.3g}", f"{r['rmse']:.3g}",
                          "-" if pd.isna(r["wb2_std"]) else f"{r['wb2_std']:.3g}", "-" if pd.isna(r["corr"]) else f"{r['corr']:.4f}"]
                         for _, r in val.iterrows()]))
        H.append("<p class='sub'>단위: 고도 m, 바람 m/s, 기온 K, 기압 hPa, 강수 mm/일, 비습 kg/kg, 해빙 비율. "
                 "기압면 장의 차이는 4시각 평균과 24시각 평균의 차이에서 온다.</p>")
    H.append(f"<p class='sub'>탐지된 사건 목록: 우랄블로킹 {len(ub_all)}건(<code>outputs/events_ural_blocking.csv</code>), "
             f"SSW {len(ssw_all)}건(<code>outputs/events_ssw.csv</code>). 다시 만들기: <code>python -m src.run --end {end}</code></p>")

    html = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>한반도 기온·강수 원인 규명 {end}</title><style>{CSS}</style></head><body><main>"
            + "\n".join(H) + "</main></body></html>")
    C.REPORTS.mkdir(exist_ok=True)
    out = C.REPORTS / f"report_{end}.html"
    out.write_text(html, encoding="utf-8")
    (C.REPORTS / "latest.html").write_text(html, encoding="utf-8")
    return out
