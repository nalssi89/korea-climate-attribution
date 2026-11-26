// 대시보드 '강제인자' 영역: site/data/forcing.json만 읽는다. 문장과 수치는 파이프라인(src/forcing.py)이 계산한 값이다.
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const S = { F: null, coast: null, target: "korea_t", season: "month", lag: 1, map: "sst" };
const PERS = [["last7", "최근 7일"], ["last30", "최근 30일"], ["month", "이번 달"], ["pentad", "이번 반순"]];
const MAP_ORDER = ["sst", "ci", "snowc", "swvl1", "t2m", "skt"];
const MAP_SHORT = { sst: "해수면온도", ci: "해빙", snowc: "눈덮임", swvl1: "토양수분", t2m: "육지 기온", skt: "지면온도(월)" };
const MAP_FIELD = { sst: "sst", ci: "ci", snowc: "snowc", swvl1: "swvl1", t2m: "t2m", skt: "skt" };
const getJSON = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); });
const word = (z) => !Number.isFinite(z) ? "–" : Math.abs(z) >= 1.5 ? "뚜렷" : Math.abs(z) >= 0.5 ? "다소" : "평년 수준";
const num = (v) => (v === null || v === undefined ? NaN : v);

function cell(st, f) {
  if (!st) return "<td>–</td>";
  const nd = f.unit === "σ" || f.unit === "°C" ? 2 : 1;
  return `<td><span class="${V.cls(num(st.sigma))}">${V.sgn(num(st.value), nd)}</span> <span class="small">(${V.sgn(num(st.sigma), 1, "σ")})</span></td>`;
}

function renderTable() {
  const F = S.F, rows = [];
  for (const [k, f] of Object.entries(F.forcings)) {
    const c = F.current[k]; if (!c) continue;
    const main = c.last30 || c.latest_month;
    const cells = f.monthly
      ? `<td>–</td><td><span class="${V.cls(num(main.sigma))}">${V.sgn(num(main.value), 2)}</span> <span class="small">(${V.sgn(num(main.sigma), 1, "σ")}, ${main.month} 월평균)</span></td><td>–</td><td>–</td>`
      : PERS.map(([p]) => cell(c[p], f)).join("");
    rows.push(`<tr><td>${f.label}</td><td>${f.unit}</td>${cells}<td>${V.fmt(num(main.percentile), 0)}</td><td>${word(num(main.sigma))}</td></tr>`);
  }
  $("fcTable").innerHTML = `<table><thead><tr><th>지수</th><th>단위</th>${PERS.map(([, l]) => `<th>${l}</th>`).join("")}<th>백분위</th><th>판정</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  const sub = F.substitute;
  $("fcTableNote").innerHTML = `편차(σ). σ와 백분위는 1979년 이후 같은 날짜 구간 대비, 평년 1991~2020. 백분위·판정은 최근 30일(지면온도는 최근 월) 기준. ` +
    `이번 달·이번 반순은 ${F.end}까지만 포함한 진행 중 값. ${F.snow_definition}. ` +
    (sub ? `지면온도는 CDS 월평균(${F.skt_last}까지)이라 일 단위 칸은 같은 영역 육지 2 m 기온으로 본다(두 지수의 월 상관 ${V.fmt(sub.r, 2)}).` : "지면온도 월평균이 없어 육지 2 m 기온으로 대신했다.");
}

function renderControls() {
  const F = S.F, sel = $("fcTarget");
  if (!sel.options.length) for (const [k, l] of Object.entries(F.targets)) sel.add(new Option(l, k));
  sel.value = S.target;
  const tabs = (el, items, cur, set) => {
    el.innerHTML = "";
    for (const [v, l] of items) { const b = document.createElement("button"); b.type = "button"; b.textContent = l; b.className = v === cur ? "on" : "";
      b.setAttribute("aria-pressed", v === cur); b.onclick = () => { set(v); renderBars(); renderControls(); }; el.appendChild(b); }
  };
  tabs($("fcSeason"), [["month", `대상 ${F.target_month}월`], ["ext", "11~3월 묶음"]], S.season, (v) => (S.season = v));
  tabs($("fcLag"), F.lags.map((L) => [L, L === 0 ? "같은 달" : `${L}개월 앞`]), S.lag, (v) => (S.lag = v));
}

function renderBars() {
  const F = S.F, keys = Object.keys(F.forcings);
  const rows = F.lagcorr.filter((r) => r.season === S.season && r.target === S.target && r.lag === S.lag)
    .sort((a, b) => keys.indexOf(a.forcing) - keys.indexOf(b.forcing))
    .map((r) => ({ label: F.forcings[r.forcing].label, value: r.r, lo: r.lo, hi: r.hi, faded: r.verdict !== "유의함",
      note: `95% ${V.sgn(r.lo, 2)} ~ ${V.sgn(r.hi, 2)} · p ${V.fmt(r.p, 3)} · FDR q ${V.fmt(r.q, 2)}${r.fdr ? " (통과)" : ""} · 표본 ${r.n} · ${r.verdict}` }));
  const when = S.season === "month" ? `${F.target_month}월` : "11~3월";
  V.barChart($("fcBars"), rows, { title: `${when} ${F.targets[S.target]}와의 상관 r (${S.lag === 0 ? "같은 달" : S.lag + "개월 앞"})`, unit: "", ml: 200 });
  const nsig = rows.filter((r) => !r.faded).length;
  $("fcBarNote").innerHTML = `1979~${F.last_year}년 월평균, 달별 선형 추세 제거. 선: 해(겨울) 단위 부트스트랩 95% 구간, 흐린 막대: 구간이 0을 포함(유의하지 않음). ` +
    `이 조건에서 유의한 인자 ${nsig}/${rows.length}개. 조합이 많아 약 5%는 우연히 유의하게 나오므로 FDR 통과 여부를 함께 본다(막대에 마우스를 올리면 표시). 상관은 인과가 아니다.`;
}

function renderMap() {
  const F = S.F, tabs = $("fcMapTabs"); tabs.innerHTML = "";
  for (const k of MAP_ORDER) {
    if (!F.maps[k]) continue;
    const b = document.createElement("button"); b.type = "button"; b.textContent = MAP_SHORT[k]; b.className = k === S.map ? "on" : "";
    b.onclick = () => { S.map = k; renderMap(); }; tabs.appendChild(b);
  }
  const M = F.maps[S.map]; if (!M) return;
  const G = V.decode(M), vmax = V.niceMax(G.a);
  const boxes = Object.values(F.forcings).filter((f) => f.field === MAP_FIELD[S.map] || (S.map === "t2m" && f.field === "t2m")).map((f) => [Math.max(f.region[0], 15), f.region[1], f.region[2], f.region[3]]);
  V.drawMap($("fcMap"), { grid: G, proj: V.polar(15, 120), vmax, coast: S.coast["110m"], boxes, marker: [36, 127.5] });
  V.legend($("fcLegend"), vmax, M.unit);
  $("fcMapNote").textContent = `${M.label} 편차 · ${M.period === "최근 30일" ? `최근 30일(${F.end}까지)` : M.period + " 월평균"} · 평년 1991~2020 · 점선: 지수 영역 · 회색: 해당 없음(바다/육지, 평년에도 얼음·눈이 없는 곳)`;
  V.hover($("fcMap"), $("fcTip"), (lat, lon) => { const v = V.sample(G, lat, lon); return Number.isFinite(v) ? `${V.llText(lat, lon)}<br>${V.sgn(v, 2, " " + M.unit)}` : null; });
}

function render() {
  const F = S.F;
  const s = F.sentences;
  $("fcSent").innerHTML = [s.overview, ...s.lag.filter((x) => /한반도|동아시아/.test(x)), ...s.regression, ...s.implication].map((x) => `<li>${x}</li>`).join("");
  $("fcState").innerHTML = s.state.map((x) => `<li>${x}</li>`).join("");
  renderTable(); renderControls(); renderBars(); renderMap();
}

$("fcTarget").onchange = (e) => { S.target = e.target.value; renderBars(); };
new MutationObserver(() => S.F && renderMap()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => S.F && renderMap());
let rt = null; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => S.F && renderMap(), 200); });

(async () => {
  try { [S.F, S.coast] = await Promise.all([getJSON("data/forcing.json"), getJSON("data/coast.json")]); }
  catch (e) { $("forcingSec").querySelector(".card").innerHTML = `<p class="small">강제인자 자료를 불러오지 못했다: ${e.message}</p>`; return; }
  S.season = "month";
  render();
})();
})();
