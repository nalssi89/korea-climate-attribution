// 북반구 3D 모식도. 모든 모양은 ../data/schematic.json의 일별 값에서 계산한다.
// 층 높이(지구 반지름 1 기준): 지상 1.004, 500 hPa 1.10, 250 hPa 1.17, 10 hPa 1.32 (보기 쉽게 과장).
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const R = { sfc: 1.004, mid: 1.10, jet: 1.17, strat: 1.32 };
const D2R = Math.PI / 180;
let D, coast, T = 0, playing = false, lastTick = 0, range = null;

// ---------------------------------------------------------------- 테마
const THEMES = ["", "light", "dark"], TNAME = { "": "시스템", light: "밝음", dark: "어둠" };
function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("theme", t) : localStorage.removeItem("theme"); } catch (e) { /* 저장 불가 */ }
  $("themeBtn").textContent = "테마: " + TNAME[t];
  if (scene) applyTheme();
}
$("themeBtn").onclick = () => setTheme(THEMES[(THEMES.indexOf(document.documentElement.dataset.theme || "") + 1) % 3]);

if (typeof THREE === "undefined") { $("hud").textContent = "three.js를 불러오지 못했다 (cdnjs.cloudflare.com 연결 확인)."; return; }

// ---------------------------------------------------------------- 장면
const stage = $("stage");
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
stage.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 50);
const cam = { az: 120 * D2R, el: 52 * D2R, dist: 4.2 };
const root = new THREE.Group(); scene.add(root);
// 지구 좌표계: y가 북극, 경도 0이 +x
const xyz = (lat, lon, r) => { const la = lat * D2R, lo = lon * D2R; return new THREE.Vector3(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo)); };
scene.add(new THREE.AmbientLight(0xffffff, 0.85));
const sun = new THREE.DirectionalLight(0xffffff, 0.35); sun.position.set(2, 3, 2); scene.add(sun);

const groups = {}; for (const k of ["base", "strat", "jet", "mid", "sfc", "col"]) { groups[k] = new THREE.Group(); root.add(groups[k]); }
const labels = [];   // {el, pos: Vector3, group}
const globeMat = new THREE.MeshLambertMaterial({ color: 0xdfe6ec });
const globe = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), globeMat); groups.base.add(globe);
const coastMat = new THREE.LineBasicMaterial({ color: 0x404040 });
const gridMat = new THREE.LineBasicMaterial({ color: 0x9aa4ad, transparent: true, opacity: 0.35 });

function applyTheme() {
  const dark = V.isDark();
  globeMat.color.set(dark ? 0x1f2a33 : 0xdfe6ec);
  coastMat.color.set(dark ? 0xc8d0d6 : 0x3a3a3a);
  gridMat.color.set(dark ? 0x56616b : 0x9aa4ad);
  if (D) draw();
}

function lineFrom(points, mat) { return new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), mat); }
function baseLayer() {
  for (const ln of coast["110m"]) {
    const pts = []; for (let i = 0; i < ln.length; i += 2) pts.push(xyz(ln[i + 1], ln[i], 1.0015));
    groups.base.add(lineFrom(pts, coastMat));
  }
  for (const la of [0, 30, 60]) { const p = []; for (let lo = 0; lo <= 360; lo += 4) p.push(xyz(la, lo, 1.002)); groups.base.add(lineFrom(p, gridMat)); }
  for (let lo = 0; lo < 360; lo += 30) { const p = []; for (let la = -30; la <= 90; la += 4) p.push(xyz(la, lo, 1.002)); groups.base.add(lineFrom(p, gridMat)); }
}

// ---------------------------------------------------------------- 자료 도구
let F = {};
const day = (name) => V.slice(F[name], T);
const ser = (k) => (D.series[k] ? D.series[k][T] : NaN);
const dateOf = (i) => new Date(new Date(D.start + "T00:00:00Z").getTime() + i * 864e5).toISOString().slice(0, 10);
const col = (t, rev) => { const [r, g, b] = V.divColor(t, rev); return new THREE.Color(r / 255, g / 255, b / 255); };

// 위경도 격자 판을 구면 껍질로 만든다. 값에 따라 색과 투명도를 준다.
function shell(G, r, vmax, opt = {}) {
  const geo = new THREE.BufferGeometry(), pos = [], colr = [], idx = [];
  const nl = G.nlat, nm = G.nlon + (opt.wrap === false ? 0 : 1);
  for (let i = 0; i < nl; i++) for (let j = 0; j < nm; j++) {
    const lat = G.lat0 + i * G.dlat, lon = G.lon0 + (j % (G.nlon + (opt.wrap === false ? 1 : 0))) * G.dlon;
    const v = G.a[i * G.nlon + (j % G.nlon)];
    const p = xyz(lat, lon, r); pos.push(p.x, p.y, p.z);
    const t = Number.isFinite(v) ? Math.max(-1, Math.min(1, v / vmax)) : 0;
    const c = col(Math.round(t * 4) / 4, opt.reverse); const a = Number.isFinite(v) ? Math.min(1, Math.abs(t) * 1.3) * (opt.alpha || 0.85) : 0;
    colr.push(c.r, c.g, c.b, a);
  }
  for (let i = 0; i < nl - 1; i++) for (let j = 0; j < nm - 1; j++) {
    const a = i * nm + j, b = a + 1, c = a + nm, d = c + 1; idx.push(a, c, b, b, c, d);
  }
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.Float32BufferAttribute(colr, 4));
  geo.setIndex(idx);
  const mat = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, side: THREE.DoubleSide, depthWrite: false });
  return new THREE.Mesh(geo, mat);
}

// 마칭 스퀘어로 등치선 (위경도 격자, 경도 순환)
function contour(G, level) {
  const segs = [], W = G.nlon, A = G.a;
  const v = (i, j) => A[i * W + (j % W)];
  const P = (i, j) => [G.lat0 + i * G.dlat, G.lon0 + j * G.dlon];
  for (let i = 0; i < G.nlat - 1; i++) for (let j = 0; j < W; j++) {
    const q = [v(i, j), v(i, j + 1), v(i + 1, j + 1), v(i + 1, j)];
    if (q.some((x) => !Number.isFinite(x))) continue;
    const c = [P(i, j), P(i, j + 1), P(i + 1, j + 1), P(i + 1, j)];
    const pts = [];
    for (let e = 0; e < 4; e++) {
      const a = q[e], b = q[(e + 1) % 4];
      if ((a < level) !== (b < level)) { const f = (level - a) / (b - a); pts.push([c[e][0] + f * (c[(e + 1) % 4][0] - c[e][0]), c[e][1] + f * (c[(e + 1) % 4][1] - c[e][1])]); }
    }
    if (pts.length === 2) segs.push(pts);
    else if (pts.length === 4) segs.push([pts[0], pts[1]], [pts[2], pts[3]]);
  }
  return segs;
}

function arrow(from, to, color, width = 0.012, opacity = 1) {
  const g = new THREE.Group(), dir = new THREE.Vector3().subVectors(to, from), len = dir.length();
  if (len < 1e-4) return g;
  const mat = new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(width, width, len * 0.72, 6), mat);
  const head = new THREE.Mesh(new THREE.ConeGeometry(width * 2.6, len * 0.28, 8), mat);
  const up = new THREE.Vector3(0, 1, 0), q = new THREE.Quaternion().setFromUnitVectors(up, dir.clone().normalize());
  shaft.quaternion.copy(q); head.quaternion.copy(q);
  shaft.position.copy(from).addScaledVector(dir, 0.36); head.position.copy(from).addScaledVector(dir, 0.86);
  g.add(shaft, head); return g;
}
function label(text, pos, group, color) {
  const el = document.createElement("div"); el.className = "lbl"; el.textContent = text; if (color) el.style.color = color;
  stage.appendChild(el); labels.push({ el, pos, group });
}
function clear(g) {
  while (g.children.length) { const c = g.children.pop(); c.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); }
}

// ---------------------------------------------------------------- 그날의 층
function draw() {
  for (const k of ["strat", "jet", "mid", "sfc", "col"]) clear(groups[k]);
  for (const l of labels) l.el.remove(); labels.length = 0;
  const dark = V.isDark(), ink = dark ? 0xf0f0f0 : 0x191919;
  const warm = dark ? "#eb6263" : "#c8393a", cool = dark ? "#4f9bf0" : "#2370cd";

  // --- 성층권 10 hPa: 극소용돌이 가장자리(그날 평년 60°N 동서평균 고도 등치선), 중심, 승온
  const z10 = day("z10"), edge = D.z10_edge[T];
  const edgeMat = new THREE.LineBasicMaterial({ color: dark ? 0x9dc8f7 : 0x1757ac });
  for (const [a, b] of contour(z10, edge)) groups.strat.add(lineFrom([xyz(a[0], a[1], R.strat), xyz(b[0], b[1], R.strat)], edgeMat));
  // 소용돌이 안쪽을 반투명하게 채운다 (가장자리보다 낮은 고도)
  const inside = { ...z10, a: z10.a.map((v) => (v < edge ? -(edge - v) : NaN)) };
  groups.strat.add(shell(inside, R.strat - 0.002, 900, { alpha: 0.55 }));
  const vlat = ser("vortex_lat"), vlon = ser("vortex_lon"), pieces = ser("vortex_pieces");
  if (Number.isFinite(vlat)) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.022, 16, 12), new THREE.MeshBasicMaterial({ color: dark ? 0x9dc8f7 : 0x0e3d7e }));
    m.position.copy(xyz(vlat, vlon, R.strat)); groups.strat.add(m);
    label(pieces >= 2 ? "극소용돌이 (분리)" : "극소용돌이", xyz(vlat, vlon, R.strat + 0.06), "strat", cool);
  }
  const t10 = ser("t10_cap_anom");
  if (Number.isFinite(t10) && t10 > 3) {
    const glow = new THREE.Mesh(new THREE.CircleGeometry(0.18 + Math.min(t10, 40) / 80, 48),
      new THREE.MeshBasicMaterial({ color: warm, transparent: true, opacity: Math.min(0.15 + t10 / 40, 0.7), side: THREE.DoubleSide, depthWrite: false }));
    glow.rotation.x = -Math.PI / 2; glow.position.set(0, R.strat + 0.004, 0); groups.strat.add(glow);
    label(`극관 승온 +${t10.toFixed(0)} K`, new THREE.Vector3(0, R.strat + 0.1, 0), "strat", warm);
  }
  // 60°N 동서풍 세기: 링 굵기와 색
  const u = ser("u1060"); const ring = [];
  for (let lo = 0; lo <= 360; lo += 4) ring.push(xyz(60, lo, R.strat));
  const ringCol = u >= 0 ? (dark ? 0x338ced : 0x257de0) : (dark ? 0xeb6263 : 0xc8393a);
  const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(ring, true), 90, 0.004 + Math.min(Math.abs(u), 60) / 60 * 0.012, 6, true),
    new THREE.MeshBasicMaterial({ color: ringCol, transparent: true, opacity: 0.75 }));
  groups.strat.add(tube);

  // --- 250 hPa 제트 축: 경도마다 20~70°N에서 동서풍 최대 위도 (30 m/s 이상만)
  const u250 = day("u250"), jetMat = new THREE.MeshBasicMaterial({ color: dark ? 0xe76624 : 0xf47230 });
  let seg = [];
  const flush = () => { if (seg.length > 2) groups.jet.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(seg), seg.length * 3, 0.008, 6, false), jetMat)); seg = []; };
  for (let j = 0; j <= u250.nlon; j++) {
    const jj = j % u250.nlon; let best = -1, bl = 0;
    for (let i = 0; i < u250.nlat; i++) { const la = u250.lat0 + i * u250.dlat; if (la < 20 || la > 70) continue; const v = u250.a[i * u250.nlon + jj]; if (v > best) { best = v; bl = la; } }
    if (best >= 30) seg.push(xyz(bl, u250.lon0 + j * u250.dlon, R.jet)); else flush();
  }
  flush();

  // --- 500 hPa: 고도 편차 껍질, 우랄 블로킹, 파동활동 플럭스
  groups.mid.add(shell(day("z500_anom"), R.mid, 240, { alpha: 0.7 }));
  const fx = day("waf_fx"), fy = day("waf_fy"), mags = [];
  for (let k = 0; k < fx.a.length; k++) if (Number.isFinite(fx.a[k]) && Number.isFinite(fy.a[k])) mags.push(Math.hypot(fx.a[k], fy.a[k]));
  mags.sort((a, b) => a - b); const ref = mags[Math.floor(mags.length * 0.95)] || 1, thr = mags[Math.floor(mags.length * 0.6)] || 0;
  for (let i = 0; i < fx.nlat; i++) for (let j = 0; j < fx.nlon; j++) {
    const k = i * fx.nlon + j, a = fx.a[k], b = fy.a[k]; if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
    const m = Math.hypot(a, b); if (m < thr) continue;
    const lat = fx.lat0 + i * fx.dlat, lon = fx.lon0 + j * fx.dlon, L = Math.min(m / ref, 1.3) * 7;
    groups.mid.add(arrow(xyz(lat, lon, R.mid + 0.01), xyz(lat + b / m * L, lon + a / m * L / Math.cos(lat * D2R), R.mid + 0.01), ink, 0.004, 0.85));
  }
  if (ser("blocked") >= 1) label(`우랄 블로킹 (Z500 ${V.sgn(ser("ural"), 0, " m")})`, xyz(62, 60, R.mid + 0.07), "mid", warm);

  // --- 지상: 동아시아 기온 편차, 시베리아 고기압·알류샨 저기압, 한기 남하
  groups.sfc.add(shell(day("t2m_anom"), R.sfc + 0.002, 6, { alpha: 0.9, wrap: false }));
  groups.sfc.add(shell(day("sst_anom"), R.sfc + 0.001, 2.5, { alpha: 0.9, wrap: false }));
  const sh = ser("siberian_high"), al = ser("aleutian");
  if (Number.isFinite(sh)) label(`H ${V.sgn(sh, 1)}`, xyz(50, 100, R.sfc + 0.03), "sfc", sh >= 0 ? warm : cool);
  if (Number.isFinite(al)) label(`L ${V.sgn(al, 1)}`, xyz(50, 190, R.sfc + 0.03), "sfc", al <= 0 ? cool : warm);
  const kt = ser("korea_t");
  if (sh > 0 && kt < 0) {   // 규칙: 시베리아 고기압이 평년보다 강하고 한반도가 평년보다 추울 때만
    const op = Math.min(0.35 + -kt / 6, 1);
    groups.sfc.add(arrow(xyz(52, 108, R.sfc + 0.02), xyz(37, 126, R.sfc + 0.02), dark ? 0x9dc8f7 : 0x1757ac, 0.01, op));
    label("한기 남하", xyz(46, 112, R.sfc + 0.06), "sfc", cool);
  }
  label(`Niño3.4 ${V.sgn(ser("nino34"), 2, "°C")}`, xyz(0, 205, R.sfc + 0.05), "sfc");

  // --- 극관 기둥: 층별 극관 고도 표준화 편차
  const P = D.pch, nl = P.levels.length;
  for (let l = 0; l < nl; l++) {
    const v = P.v[T * nl + l]; if (v === null) continue;
    const s = v * 0.1, p = P.levels[l];
    const h = R.sfc + (Math.log(1000) - Math.log(p)) / (Math.log(1000) - Math.log(10)) * (R.strat - R.sfc);
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.016, 24), new THREE.MeshBasicMaterial({ color: col(Math.max(-1, Math.min(1, s / 3))), transparent: true, opacity: 0.95 }));
    disc.position.set(0, h, 0); groups.col.add(disc);
  }
  hud();
}

function hud() {
  const d = dateOf(T), mk = D.marks.filter((m) => m.date === d).map((m) => m.label);
  $("hud").innerHTML = `<div class="d">${d}</div>` +
    `10 hPa 60°N 동서풍 <b>${V.fmt(ser("u1060"), 1)}</b> m/s · 극관 T10 편차 ${V.sgn(ser("t10_cap_anom"), 1, " K")}<br>` +
    `우랄 Z500 ${V.sgn(ser("ural"), 0, " m")}${ser("blocked") >= 1 ? " (블로킹)" : ""} · AO ${V.sgn(ser("ao"), 2)} · Niño3.4 ${V.sgn(ser("nino34"), 2, "°C")}<br>` +
    `한반도 기온 ${V.sgn(ser("korea_t"), 1, "°C")} · 동아시아 ${V.sgn(ser("ea_t"), 1, "°C")}` + (mk.length ? `<br><span class="ev">● ${mk.join(", ")}</span>` : "");
  $("slider").value = T;
}

// ---------------------------------------------------------------- 카메라·조작
function place() {
  camera.position.set(cam.dist * Math.cos(cam.el) * Math.cos(cam.az), cam.dist * Math.sin(cam.el), -cam.dist * Math.cos(cam.el) * Math.sin(cam.az));
  camera.lookAt(0, 0.35, 0);
}
function resize() {
  const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
const ptrs = new Map(); let pinch0 = 0;
renderer.domElement.addEventListener("pointerdown", (e) => { ptrs.set(e.pointerId, [e.clientX, e.clientY]); renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener("pointerup", (e) => { ptrs.delete(e.pointerId); pinch0 = 0; });
renderer.domElement.addEventListener("pointercancel", (e) => { ptrs.delete(e.pointerId); pinch0 = 0; });
renderer.domElement.addEventListener("pointermove", (e) => {
  if (!ptrs.has(e.pointerId)) return;
  const [x0, y0] = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  if (ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch0) cam.dist = Math.max(1.8, Math.min(9, cam.dist * pinch0 / d)); pinch0 = d; return;
  }
  cam.az -= (e.clientX - x0) * 0.008; cam.el = Math.max(-0.2, Math.min(1.5, cam.el + (e.clientY - y0) * 0.006));
});
renderer.domElement.addEventListener("wheel", (e) => { e.preventDefault(); cam.dist = Math.max(1.8, Math.min(9, cam.dist * (1 + Math.sign(e.deltaY) * 0.08))); }, { passive: false });
$("resetBtn").onclick = () => Object.assign(cam, { az: 120 * D2R, el: 52 * D2R, dist: 4.2 });

const proj = new THREE.Vector3();
function loop(ts) {
  requestAnimationFrame(loop);
  if (playing && ts - lastTick > 1000 / +$("speedSel").value) {
    lastTick = ts; const lo = range ? range[0] : 0, hi = range ? range[1] : D.n - 1;
    T = T >= hi || T < lo ? lo : T + 1; draw();
  }
  place(); renderer.render(scene, camera);
  const w = stage.clientWidth, h = stage.clientHeight, camDir = camera.position.clone().normalize();
  for (const l of labels) {
    if (!groups[l.group].visible) { l.el.style.display = "none"; continue; }
    proj.copy(l.pos).project(camera);
    const behind = l.pos.clone().normalize().dot(camDir) < -0.1 && l.pos.length() < 1.2;
    l.el.style.display = behind || proj.z > 1 ? "none" : "block";
    l.el.style.left = (proj.x + 1) / 2 * w + "px"; l.el.style.top = (1 - proj.y) / 2 * h + "px";
  }
}

// ---------------------------------------------------------------- 시작
(async () => {
  try {
    [D, coast] = await Promise.all([fetch("../data/schematic.json").then((r) => r.json()), fetch("../data/coast.json").then((r) => r.json())]);
  } catch (e) { $("hud").textContent = "자료를 불러오지 못했다: " + e.message; return; }
  for (const [k, g] of Object.entries(D.fields)) F[k] = V.decode(g);
  baseLayer();
  $("slider").max = D.n - 1;
  const q = new URLSearchParams(location.search), idx = (d) => Math.round((Date.parse(d + "T00:00:00Z") - Date.parse(D.start + "T00:00:00Z")) / 864e5);
  if (q.get("start") && q.get("end")) {
    const a = Math.max(0, idx(q.get("start"))), b = Math.min(D.n - 1, idx(q.get("end")));
    if (b >= a && b >= 0) { range = [a, b]; T = b; $("rangeInfo").textContent = `대시보드 기간 ${q.get("start")} ~ ${q.get("end")} (재생은 이 구간 반복)`; }
  }
  if (!range) { T = D.n - 1; $("rangeInfo").textContent = `${D.start} ~ ${D.end} (${D.n}일)`; }
  // 사건 표식
  const tk = $("ticks"), pct = (i) => (i / (D.n - 1)) * 100 + "%";
  for (const m of D.marks) { const i = idx(m.date); if (i < 0 || i >= D.n) continue; const s = document.createElement("span"); s.className = m.kind; s.style.left = pct(i); s.textContent = m.kind === "ssw" ? "SSW" : "블로킹"; s.title = `${m.date} ${m.label}`; tk.appendChild(s); }
  if (range) for (const i of range) { const s = document.createElement("span"); s.className = "sel"; s.style.left = pct(i); s.textContent = i === range[0] ? "시작" : "끝"; tk.appendChild(s); }
  $("slider").oninput = (e) => { T = +e.target.value; draw(); };
  $("playBtn").onclick = () => { playing = !playing; $("playBtn").textContent = playing ? "❚❚ 정지" : "▶ 재생"; $("playBtn").setAttribute("aria-pressed", playing); };
  const jump = (s) => { T = Math.max(0, Math.min(D.n - 1, T + s * +$("jumpSel").value)); draw(); };
  $("backBtn").onclick = () => jump(-1); $("fwdBtn").onclick = () => jump(1);
  for (const cb of document.querySelectorAll("[data-l]")) cb.onchange = () => { groups[cb.dataset.l].visible = cb.checked; };
  $("keys").innerHTML = [
    `<div><span class="sw" style="background:var(--cool)"></span>10 hPa 극소용돌이: 그날 평년 60°N 동서평균 고도보다 낮은 영역과 가장자리 등치선, 점은 중심</div>`,
    `<div><span class="sw" style="background:var(--s1)"></span>60°N 고리: 10 hPa 동서풍 (굵기 = 세기, 빨강 = 동풍 역전)</div>`,
    `<div><span class="sw" style="background:var(--warm)"></span>극 원판: 극관 10 hPa 기온 편차가 +3 K 넘을 때 승온 표시</div>`,
    `<div><span class="sw" style="background:var(--s2)"></span>250 hPa 제트 축: 경도마다 20~70°N 최대풍 위치(30 m/s 이상)</div>`,
    `<div><span class="sw" style="background:linear-gradient(90deg,var(--cool),var(--warm))"></span>500 hPa 껍질: 고도 편차(±240 m), 검은 화살표: 7일 평균 파동활동 플럭스</div>`,
    `<div><span class="sw" style="background:linear-gradient(90deg,var(--cool),var(--warm))"></span>지상: 동아시아 2 m 기온 편차(±6°C), 열대 태평양 해수면온도 편차(±2.5°C)</div>`,
    `<div><b>H/L</b> 시베리아 고기압·알류샨 저기압 해면기압 편차(hPa). '한기 남하'는 시베리아 고기압 편차 &gt; 0이고 한반도 기온 편차 &lt; 0인 날만</div>`,
    `<div><span class="sw" style="background:linear-gradient(90deg,var(--cool),var(--warm))"></span>극관 기둥: 층별(1000~10 hPa) 극관 고도 표준화 편차(±3σ), 위에서 아래로 번지면 하향 전파</div>`,
  ].join("");
  $("notes").textContent = `자료 ${D.start} ~ ${D.end}. 높이는 과장했다(10 hPa 약 31 km를 지구 반지름의 0.32배로).`;
  setTheme(document.documentElement.dataset.theme || "");
  addEventListener("resize", resize); resize(); draw(); requestAnimationFrame(loop);
})();
})();
