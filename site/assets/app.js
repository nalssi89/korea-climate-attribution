// 대시보드: site/data/의 JSON만 읽어 그린다. 문장과 수치는 파이프라인이 계산한 값을 그대로 쓴다.
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const S = { meta: null, idx: null, ssw: null, coast: null, cache: {}, pid: null, kind: "last30",
  region: "korea", v: "t", nh: "z500", eaVar: "t2m", eaLayer: "obs" };
const NH_ORDER = ["z500", "msl", "t850", "u250", "z10", "t10", "waf"];
const NH_SHORT = { z500: "Z500", msl: "해면기압", t850: "T850", u250: "U250", z10: "Z10", t10: "T10", waf: "파동활동 플럭스" };
const KIND_ORDER = ["pentad", "week", "month", "last7", "last30"];
const KIND_LABEL = { pentad: "반순", week: "주", month: "월", last7: "최근 7일", last30: "최근 30일" };
const IDX_ROWS = ["ural", "blocked", "u1060", "pv", "t10_cap_anom", "vt100_anom", "pch10", "pch100", "pch500", "nino34",
  "ao", "nao", "pna", "wp", "eu", "scand", "siberian_high", "aleutian", "ea_jet", "eawm", "phil_sea", "bk_ice"];

const getJSON = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); });
const sigWord = (z) => { const r = S.meta.rules; if (!Number.isFinite(z)) return "–";
  return Math.abs(z) >= r.sigma_strong ? "뚜렷" : Math.abs(z) >= r.sigma_weak ? "다소" : "평년 수준"; };

// ---------------------------------------------------------------- 테마
const THEMES = ["", "light", "dark"], TNAME = { "": "시스템", light: "밝음", dark: "어둠" };
const setTheme = (t) => {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("theme", t) : localStorage.removeItem("theme"); } catch (e) { /* 저장 불가 */ }
  $("themeBtn").textContent = "테마: " + TNAME[t];
};
$("themeBtn").onclick = () => { const cur = document.documentElement.dataset.theme || ""; setTheme(THEMES[(THEMES.indexOf(cur) + 1) % 3]); redraw(); };
setTheme(document.documentElement.dataset.theme || "");
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => redraw());

// ---------------------------------------------------------------- 상태 ↔ 주소
const readHash = () => { const h = new URLSearchParams(location.hash.slice(1)); for (const k of ["pid", "region", "v", "nh"]) if (h.get(k)) S[k] = h.get(k); };
const writeHash = () => { history.replaceState(null, "", "#" + new URLSearchParams({ pid: S.pid, region: S.region, v: S.v, nh: S.nh })); };

const periodsOf = (kind) => S.meta.periods.filter((p) => p.kind === kind);
const curPeriod = () => S.meta.periods.find((p) => p.pid === S.pid);

async function loadPeriod(pid) {
  if (!S.cache[pid]) S.cache[pid] = await getJSON(`data/periods/${pid}.json`);
  return S.cache[pid];
}

// ---------------------------------------------------------------- 그리기
function renderControls() {
  const tabs = $("kindTabs"); tabs.innerHTML = "";
  for (const k of KIND_ORDER) {
    if (!periodsOf(k).length) continue;
    const b = document.createElement("button"); b.type = "button"; b.textContent = KIND_LABEL[k];
    b.className = k === S.kind ? "on" : ""; b.setAttribute("aria-pressed", k === S.kind);
    b.onclick = () => { S.kind = k; S.pid = periodsOf(k)[0].pid; update(); };
    tabs.appendChild(b);
  }
  const list = periodsOf(S.kind), i = list.findIndex((p) => p.pid === S.pid), p = list[i];
  $("prevBtn").disabled = i >= list.length - 1; $("nextBtn").disabled = i <= 0;
  $("prevBtn").onclick = () => { S.pid = list[i + 1].pid; update(); };
  $("nextBtn").onclick = () => { S.pid = list[i - 1].pid; update(); };
  $("periodLabel").textContent = p.label;
  $("periodState").textContent = p.complete ? `${p.n_days}일 · 완결` : `진행 중 · ${p.full_days}일 중 ${p.n_days}일(${p.eff_end}까지)`;
  $("schemLink").href = `schematic/?start=${p.start}&end=${p.eff_end}`;
}

function renderSummary(P) {
  const tiles = $("tiles"); tiles.innerHTML = "";
  for (const r of P.regions) {
    const d = document.createElement("div"); d.className = "tile";
    d.innerHTML = `<div class="k">${r.name}</div><div class="v ${V.cls(r.t.value)}">${V.sgn(r.t.value, 1, "°C")}</div>` +
      `<div class="n">${V.sgn(r.t.sigma, 1, "σ")} · 백분위 ${V.fmt(r.t.percentile, 0)} · 강수 ${V.fmt(r.p_ratio, 0)}%</div>`;
    tiles.appendChild(d);
  }
  $("sentences").innerHTML = P.sentences.map((s) => `<li>${s}</li>`).join("");
}

function renderBars(P) {
  const sel = $("regionSel");
  if (!sel.options.length) for (const r of S.meta.regions) sel.add(new Option(r.name, r.key));
  sel.value = S.region;
  const col = `${S.region}_${S.v}`, a = P.attribution.targets[col];
  const unit = a.unit, rows = a.factors.map((f) => ({ label: f.label, value: f.contribution, lo: f.lo, hi: f.hi,
    faded: f.verdict !== "유의함", note: `지수 ${V.sgn(f.z, 2, "σ")}, 계수 ${V.sgn(f.coef, 2)}/σ, 시차 ${f.lag_days}일 · ${f.verdict}` }));
  rows.push({ label: "잔차", value: a.residual, kind: "resid" }, { label: "관측 편차", value: a.observed, kind: "obs" });
  const reg = S.meta.regions.find((r) => r.key === S.region).name;
  V.barChart($("barChart"), rows, { title: `${reg} ${S.v === "t" ? "기온" : "강수"} 기여도 (${unit})`, unit });
  $("barNote").innerHTML = `회귀로 설명 ${V.sgn(a.predicted, 2, " " + unit)}, 잔차 ${V.sgn(a.residual, 2, " " + unit)} · R² ${V.fmt(a.r2, 2)}, ` +
    `교차검증 R² <b>${V.fmt(a.r2_cv, 2)}</b> · 표본 ${a.n_samples}개(${a.n_years}개 해) · 선: 부트스트랩 5~95%, 흐린 막대: 구간이 0을 포함(유의하지 않음). 장기 추세에는 절편을 합쳤다.`;
  const R = S.meta.r2_by_kind;
  $("r2Table").innerHTML = `<table><thead><tr><th>단위</th><th>일수</th><th>한반도 기온</th><th>한반도 강수</th><th>동아시아 기온</th><th>동아시아 강수</th></tr></thead><tbody>` +
    R.map((r) => `<tr><td>${r.kind_label}</td><td>${r.n_days}</td><td>${V.fmt(r.r2cv_korea_t, 2)}</td><td>${V.fmt(r.r2cv_korea_p, 2)}</td><td>${V.fmt(r.r2cv_ea_t, 2)}</td><td>${V.fmt(r.r2cv_ea_p, 2)}</td></tr>`).join("") + "</tbody></table>";
}

function renderNH(P) {
  const tabs = $("nhTabs"); tabs.innerHTML = "";
  for (const k of NH_ORDER) {
    const b = document.createElement("button"); b.type = "button"; b.textContent = NH_SHORT[k]; b.className = k === S.nh ? "on" : "";
    b.onclick = () => { S.nh = k; writeHash(); renderNH(P); }; tabs.appendChild(b);
  }
  const F = P.nh[S.nh], G = V.decode(F), vmax = V.niceMax(G.a);
  const arrows = F.arrows ? { fx: V.decode(F.arrows.fx), fy: V.decode(F.arrows.fy) } : null;
  V.drawMap($("nhMap"), { grid: G, proj: V.polar(15, 120), vmax, coast: S.coast["110m"], arrows, marker: [36, 127.5],
    boxes: S.nh === "z500" ? [[50, 70, 40, 80]] : null });
  V.legend($("nhLegend"), vmax, F.unit);
  $("nhNote").textContent = `${F.label} 편차 (평년 ${S.meta.clim.join("~")}) · 극투영, 아래쪽이 120°E · 점: 한반도` +
    (S.nh === "z500" ? " · 점선 상자: 우랄 영역" : "") + (S.nh === "waf" ? " · 화살표: Takaya-Nakamura 플럭스(상위 45%만)" : "");
  V.hover($("nhMap"), $("nhTip"), (lat, lon) => `${V.llText(lat, lon)}<br>${V.sgn(V.sample(G, lat, lon), 1, " " + F.unit)}`);
  const rows = IDX_ROWS.filter((k) => P.indices[k]).map((k) => {
    const st = P.indices[k], lab = S.meta.index_label[k] || [k, ""];
    return `<tr><td>${lab[0]}</td><td>${k === "blocked" ? V.fmt(P.blocked_days, 0) + "일" : V.sgn(st.value, Math.abs(st.value) >= 10 ? 0 : 2)}</td><td>${lab[1]}</td>` +
      `<td class="${V.cls(st.sigma)}">${V.sgn(st.sigma, 1)}</td><td>${V.fmt(st.percentile, 0)}</td><td>${sigWord(st.sigma)}</td></tr>`;
  });
  $("idxTable").innerHTML = `<table><thead><tr><th>지수</th><th>값</th><th>단위</th><th>σ</th><th>백분위</th><th>판정</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function renderEA(P) {
  for (const b of $("eaVarTabs").children) b.className = b.dataset.v === S.eaVar ? "on" : "";
  const sel = $("eaLayerSel"); const want = [["obs", "관측 편차"], ...S.meta.factors.map((f) => ["c:" + f.key, "기여: " + f.label]), ["resid", "잔차"], ["r2cv", "교차검증 R²"]];
  if (sel.options.length !== want.length) { sel.innerHTML = ""; for (const [v, t] of want) sel.add(new Option(t, v)); }
  sel.value = S.eaLayer;
  const E = P.ea[S.eaVar];
  const raw = S.eaLayer === "obs" ? E.obs : S.eaLayer === "resid" ? E.resid : S.eaLayer === "r2cv" ? E.r2cv : E.contrib[S.eaLayer.slice(2)];
  const G = V.decode(raw), unit = S.eaLayer === "r2cv" ? "" : S.eaVar === "t2m" ? "°C" : "mm/일";
  const vmax = S.eaLayer === "r2cv" ? 1 : S.eaLayer === "obs" ? V.niceMax(G.a) : V.niceMax(V.decode(E.obs).a);
  const box = [20, 55, 100, 150];
  const boxes = S.meta.regions.filter((r) => r.key !== "ea").map((r) => r.box);
  V.drawMap($("eaMap"), { grid: G, proj: V.rect(box), vmax, reverse: S.eaVar === "tp" && S.eaLayer !== "r2cv", coast: S.coast["50m"], wrap: false, boxes, marker: [37.5, 127] });
  V.legend($("eaLegend"), vmax, unit, S.eaVar === "tp" && S.eaLayer !== "r2cv");
  $("eaNote").textContent = (S.eaLayer.startsWith("c:") ? "격자마다 같은 회귀를 적용한 인자 기여(색 범위는 관측 편차와 같다). " : "") +
    (S.eaVar === "tp" ? "강수는 많음=파랑, 적음=빨강. " : "") + "점선 상자: 하위 영역.";
  V.hover($("eaMap"), $("eaTip"), (lat, lon) => { const v = V.sample(G, lat, lon, false); return Number.isFinite(v) ? `${V.llText(lat, lon)}<br>${V.sgn(v, 2, " " + unit)}` : null; });
  $("regTable").innerHTML = `<table><thead><tr><th>영역</th><th>기온</th><th>σ</th><th>백분위</th><th>강수 평년비</th><th>강수 σ</th></tr></thead><tbody>` +
    P.regions.map((r) => `<tr><td>${r.name}</td><td class="${V.cls(r.t.value)}">${V.sgn(r.t.value, 2)}</td><td>${V.sgn(r.t.sigma, 1)}</td><td>${V.fmt(r.t.percentile, 0)}</td><td>${V.fmt(r.p_ratio, 0)}%</td><td>${V.sgn(r.p.sigma, 1)}</td></tr>`).join("") +
    "</tbody></table>";
}

function bandsFor(p) {
  const B = [];
  if (p) B.push({ start: p.start, end: p.eff_end, kind: "sel" });
  for (const e of S.idx.events.ural_blocking) B.push({ start: e.onset, end: e.end, kind: "block" });
  return B;
}
function sswMarks() {
  const c = S.ssw.case; return c.onset ? [{ date: c.onset, label: c.kind === "major" ? "SSW" : "부 승온" }] : [];
}
function renderSeries() {
  const p = curPeriod(), D = S.idx, n = D.series.u1060.length, dates = [];
  const t0 = new Date(D.start + "T00:00:00Z"); for (let i = 0; i < n; i++) dates.push(new Date(t0.getTime() + i * 864e5).toISOString().slice(0, 10));
  const g = $("tsGrid"); g.innerHTML = "";
  const s = (k) => D.series[k] || [];
  const specs = [
    { title: "10 hPa 60°N 동서평균 동서풍 (m/s)", series: [{ name: "관측", values: s("u1060"), color: "var(--s1)" }, { name: "평년", values: s("u1060_clim"), color: "var(--ink-3)", dash: "4 3", width: 1.5 }], unit: "m/s" },
    { title: "우랄 Z500 편차 (m)", series: [{ name: "우랄", values: s("ural"), color: "var(--s1)" }], unit: "m", nd: 0 },
    { title: "AO·NAO (σ)", series: [{ name: "AO", values: s("ao"), color: "var(--s1)" }, { name: "NAO", values: s("nao"), color: "var(--s2)" }], unit: "σ" },
    { title: "PNA·WP·EU·SCAND (σ)", series: [{ name: "PNA", values: s("pna"), color: "var(--s1)" }, { name: "WP", values: s("wp"), color: "var(--s2)" }, { name: "EU", values: s("eu"), color: "var(--s3)" }], unit: "σ" },
    { title: "Niño3.4 해수면온도 편차 (°C)", series: [{ name: "Niño3.4", values: s("nino34"), color: "var(--s1)" }], unit: "°C" },
    { title: "기온 편차 (°C)", series: [{ name: "한반도 ERA5", values: s("korea_t"), color: "var(--s1)" }, ...(D.series.asos_t ? [{ name: "ASOS 전국", values: s("asos_t"), color: "var(--s2)" }] : []), { name: "동아시아", values: s("ea_t"), color: "var(--s3)" }], unit: "°C" },
    { title: "시베리아 고기압 편차 (hPa)", series: [{ name: "시베리아 고기압", values: s("siberian_high"), color: "var(--s1)" }], unit: "hPa" },
    { title: "동아시아 제트(U200) 편차 (m/s)", series: [{ name: "제트", values: s("ea_jet"), color: "var(--s1)" }], unit: "m/s" },
  ];
  for (const sp of specs) {
    const c = document.createElement("div"); c.className = "card chart"; g.appendChild(c);
    V.lineChart(c, { ...sp, dates, bands: bandsFor(p), marks: sswMarks() });
  }
  S.dates = dates;
}

function renderSSW() {
  const c = S.ssw.case;
  $("sswTitle").textContent = c.title + (c.kind === "major" ? " · 주 승온" : c.kind === "minor" ? " · 부 승온" : "");
  $("sswSent").innerHTML = c.sentences.map((x) => `<li>${x}</li>`).join("");
  const D = S.idx, dates = S.dates, s = (k) => D.series[k] || [];
  const ch = $("sswCharts"); ch.innerHTML = "";
  for (const sp of [
    { title: "극관(60~90°N) 10 hPa 기온 편차 (K)", series: [{ name: "T10 극관", values: s("t10_cap_anom"), color: "var(--warm)" }], unit: "K" },
    { title: "100 hPa 에디 열속 편차 (45~75°N, K·m/s)", series: [{ name: "[v*T*] 편차", values: s("vt100_anom"), color: "var(--s2)" }], unit: "K·m/s" },
    { title: "10 hPa 60°N 파수 1·2 진폭 (m)", series: [{ name: "파수1", values: s("wave1"), color: "var(--s1)" }, { name: "파수2", values: s("wave2"), color: "var(--s2)" }], unit: "m", nd: 0, zero: true },
    { title: "10 hPa 소용돌이 중심 위도 (°N)", series: [{ name: "중심 위도", values: s("vortex_lat"), color: "var(--s4)" }], unit: "°N", zero: false },
  ]) { const d = document.createElement("div"); d.className = "card chart"; ch.appendChild(d); V.lineChart(d, { ...sp, dates, bands: bandsFor(null), marks: sswMarks() }); }
  // 극관 고도 단면
  const P = S.ssw.pch, nl = P.levels.length, nd = P.v.length / nl, rows = [];
  for (let l = 0; l < nl; l++) rows.push(P.v.slice(l * nd, (l + 1) * nd).map((x) => (x === null ? NaN : x * 0.01)));
  const pd = []; const t0 = new Date(P.start + "T00:00:00Z"); for (let i = 0; i < nd; i++) pd.push(new Date(t0.getTime() + i * 864e5).toISOString().slice(0, 10));
  V.heat($("pchCanvas"), { levels: P.levels, v: rows, vmax: 3, dates: pd, marks: c.onset ? [c.onset] : [], height: 190 });
  V.legend($("pchLegend"), 3, "σ", false, 13);
  const cv = $("pchCanvas"), tip = $("pchTip");
  cv.onpointermove = (ev) => { const r = cv.getBoundingClientRect(), k = cv._pick(ev.clientX - r.left, ev.clientY - r.top);
    if (!k || !k.date) { tip.style.display = "none"; return; }
    tip.innerHTML = `${k.date} · ${k.level} hPa<br>${V.sgn(k.v, 2, "σ")}`; tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX - r.left + 12, r.width - tip.offsetWidth - 4) + "px"; tip.style.top = ev.clientY - r.top + 12 + 40 + "px"; };
  cv.onpointerleave = () => (tip.style.display = "none");
  // 과거 이른 겨울 사례와 비교
  const H = c.detail && c.detail.history, hb = $("sswHist"); hb.innerHTML = "";
  if (H && H.n >= 2) {
    const lagDates = H.lags.map((l) => String(l));
    for (const [k, ttl, unit] of [["u1060", "10 hPa 60°N 동서풍 (m/s)", "m/s"], ["ao", "북극진동 (σ)", "σ"], ["korea_t", "한반도 기온 편차 (°C, 추세 제거)", "°C"], ["ea_t", "동아시아 기온 편차 (°C, 추세 제거)", "°C"]]) {
      const x = H.series[k]; if (!x || !x.mean) continue;
      const d = document.createElement("div"); d.className = "card chart"; hb.appendChild(d);
      V.lineChart(d, { title: `${ttl} · 발생일 기준 −20~+60일`, unit, dates: lagDates,
        series: [{ name: `과거 ${H.n}건 평균`, values: x.mean, color: "var(--ink-3)" }, { name: "5~95%", values: x.lo, color: "var(--ink-3)", dash: "2 3", width: 1 },
          { name: "", values: x.hi, color: "var(--ink-3)", dash: "2 3", width: 1 }, { name: "이번 사례", values: x.current, color: "var(--s1)", width: 2.4 }],
        marks: [{ date: "0", label: "발생일" }], xticks: ["-20", "0", "20", "40", "60"] });
    }
    const note = document.createElement("p"); note.className = "small"; note.style.gridColumn = "1/-1";
    note.textContent = `과거 사례(11~12월 주 승온): ${H.dates.join(", ")}. 가로축은 날짜가 아니라 발생일 기준 일수다. 지금은 발생 후 ${H.elapsed}일까지만 관측됐다.`;
    hb.appendChild(note);
  }
}

function renderStatic() {
  const M = S.meta;
  $("dataEnd").textContent = `자료 끝 ${M.data_end} · 생성 ${M.generated}`;
  const st = M.status || {};
  const stRows = Object.entries(st).map(([k, v]) => `<tr><td>${k}</td><td style="white-space:normal;text-align:left">${typeof v === "string" ? v : JSON.stringify(v)}</td></tr>`).join("");
  const tele = Object.entries(M.tele || {}).filter(([k]) => !k.startsWith("_")).map(([k, v]) => `${M.tele_label[k]}: 회전 EOF ${v.mode}, 맞춤 ${V.fmt(v.match, 2)}`).join(" · ");
  $("methods").innerHTML = `<ul class="sent">
<li>원인 탐색은 북반구 전체(0~90°N), 영향 평가는 동아시아(20~55°N, 100~150°E)와 하위 영역이다. 평년은 ${M.clim.join("~")}년, 과거 통계는 ${M.start_year}년 이후.</li>
<li>기간: 반순(1월 1일 시작 연 73개, 윤년 2월 29일은 제12반순), 주(월~일, ISO), 달력 월, 최근 7일·30일. 끝나지 않은 기간은 포함된 날짜까지만 쓰고 '진행 중'으로 표시한다.</li>
<li>판정 규칙: |σ| ≥ ${M.rules.sigma_strong} "뚜렷", ${M.rules.sigma_weak} ≤ |σ| &lt; ${M.rules.sigma_strong} "다소", 그 아래 "평년 수준". 부트스트랩 5~95% 구간이 0을 포함하면 "유의하지 않음".</li>
<li>기여도: 장기 추세, 우랄 Z500(5일 앞), 10 hPa 60°N 동서풍(15일 앞), Niño3.4, 바렌츠-카라 해빙(30일 앞)의 표준화 다중회귀. 인자끼리 얽혀 있어 인과를 깔끔히 나누지 못하므로 구간으로 읽는다. 강수는 설명력이 낮다.</li>
<li>사건은 자료에서 탐지한다: 우랄블로킹(30~90°E 역전 지수 5일 이상), SSW(10 hPa 60°N 동풍 역전, Charlton-Polvani), 부 승온(극관 10 hPa 기온 7일 상승 ≥ 20 K 또는 극-60°N 기온 경도 역전), 소용돌이 분리/변위(10 hPa 가장자리 안쪽 조각 수).</li>
<li>원격상관 패턴: AO는 해면기압 EOF1, 나머지는 11~3월 월평균 Z500 회전 EOF를 문헌 활동 중심과 맞춤 (${tele}).</li>
<li>SSW의 지표 영향은 보통 발생 후 수 주~두 달에 나타난다. 발생 직후의 값은 지금까지 관측된 것이고, 과거 합성은 가능성의 범위일 뿐 예측이 아니다.</li></ul>
<h3>실행 상태</h3><div class="tw"><table><tbody>${stRows}</tbody></table></div>`;
  $("footer").innerHTML = `자료: ERA5 재분석(ECMWF/Copernicus Climate Change Service, 경로: WeatherBench2·Google ARCO-ERA5·ECMWF ARCO; 최근 약 3개월은 잠정 ERA5T) · ` +
    `기상청 ASOS 일자료(기상청 API 허브, 전국 평균 편차 등 집계값만 게시) · 해안선 Natural Earth. ` +
    `이 페이지는 파이프라인(<code>python -m src.run --end YYYY-MM-DD</code>)이 만든 값만 표시한다. <a href="https://github.com/nalssi89/korea-climate-attribution">저장소</a>`;
}

let drawing = null;
async function update() {
  writeHash(); renderControls();
  const P = await loadPeriod(S.pid);
  renderSummary(P); renderBars(P); renderNH(P); renderEA(P); renderSeries();
  drawing = P;
}
function redraw() { if (!drawing) return; renderNH(drawing); renderEA(drawing); renderSSW(); }

$("regionSel").onchange = (e) => { S.region = e.target.value; writeHash(); renderBars(drawing); };
for (const b of $("varTabs").children) b.onclick = () => { S.v = b.dataset.v; for (const x of $("varTabs").children) x.className = x === b ? "on" : ""; writeHash(); renderBars(drawing); };
for (const b of $("eaVarTabs").children) b.onclick = () => { S.eaVar = b.dataset.v; renderEA(drawing); };
$("eaLayerSel").onchange = (e) => { S.eaLayer = e.target.value; renderEA(drawing); };
let rt = null; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(redraw, 200); });

(async () => {
  try {
    [S.meta, S.idx, S.ssw, S.coast] = await Promise.all(["meta", "indices", "ssw", "coast"].map((n) => getJSON(`data/${n}.json`)));
  } catch (e) {
    $("dataEnd").textContent = "자료를 불러오지 못했다: " + e.message; return;
  }
  readHash();
  if (!S.meta.periods.find((p) => p.pid === S.pid)) S.pid = S.meta.periods.find((p) => p.kind === "last30").pid;
  S.kind = curPeriod().kind;
  for (const b of $("varTabs").children) b.className = b.dataset.v === S.v ? "on" : "";
  renderStatic();
  await update();
  renderSSW();
})();
})();
