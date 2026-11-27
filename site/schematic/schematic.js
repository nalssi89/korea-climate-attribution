// 북반구 3D 모식도. 모든 모양은 ../data/schematic.json의 일별 값에서 계산한다.
// 층 높이(지구 반지름 1 기준, 보기 쉽게 과장): 지상 0.004, 500 hPa 0.10, 250 hPa 0.17, 10 hPa 0.32. '층 간격'으로 더 벌릴 수 있다.
// 격자는 3차(Catmull-Rom) 보간으로 1.5° 간격까지 촘촘하게 다시 만든 뒤 색과 등치선을 그린다.
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const H0 = { sfc: 0.004, mid: 0.10, jet: 0.17, strat: 0.32 };
const R = {};
let gap = 1;
const setR = () => { for (const k in H0) R[k] = 1 + H0[k] * (k === "sfc" ? 1 : gap); };
setR();
const D2R = Math.PI / 180;
const JET_MIN = 50;            // 제트 영역: 250 hPa 풍속 50 m/s 이상
const JET_TOP = 85;
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
const CAM0 = { az: 120 * D2R, el: 52 * D2R, dist: 4.2 };
const cam = { ...CAM0 };
const root = new THREE.Group(); scene.add(root);
// 지구 좌표계: y가 북극, 경도 0이 +x
const xyz = (lat, lon, r) => { const la = lat * D2R, lo = lon * D2R; return new THREE.Vector3(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo)); };
scene.add(new THREE.AmbientLight(0xffffff, 0.85));
const sun = new THREE.DirectionalLight(0xffffff, 0.35); sun.position.set(2, 3, 2); scene.add(sun);

const LAYERS = ["strat", "jet", "mid", "sfc", "col"];
const groups = {}; for (const k of ["base", ...LAYERS]) { groups[k] = new THREE.Group(); root.add(groups[k]); }
const labels = [];      // {el, pos: Vector3, group}
const globeMat = new THREE.MeshLambertMaterial({ color: 0xdfe6ec });
const globe = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), globeMat); groups.base.add(globe);
const coastMat = new THREE.LineBasicMaterial({ color: 0x404040 });
const gridMat = new THREE.LineBasicMaterial({ color: 0x9aa4ad, transparent: true, opacity: 0.35 });

// 화살표는 같은 원기둥·원뿔을 늘려 쓴다 (매일 다시 그려도 가볍게)
const CYL = new THREE.CylinderGeometry(1, 1, 1, 6), CONE = new THREE.ConeGeometry(1, 1, 10);
const SHARED = new Set([CYL, CONE]);

function applyTheme() {
  const dark = V.isDark();
  globeMat.color.set(dark ? 0x1f2a33 : 0xe3e8ec);
  coastMat.color.set(dark ? 0xc8d0d6 : 0x3a3a3a);
  gridMat.color.set(dark ? 0x56616b : 0x9aa4ad);
  if (D) { draw(); keys(); }
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

// ---------------------------------------------------------------- 색
const PAL = {
  jetLight: ["#ffe3b3", "#ffb35c", "#f47230", "#c2255c", "#6a1b7c"],
  jetDark: ["#fff0c2", "#ffc46b", "#ff8a3d", "#f0508a", "#c77dff"],
};
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const seqColor = (t) => {
  const pal = V.isDark() ? PAL.jetDark : PAL.jetLight, x = Math.max(0, Math.min(1, t)) * (pal.length - 1);
  const i = Math.min(Math.floor(x), pal.length - 2), d = x - i, a = hex(pal[i]), b = hex(pal[i + 1]);
  return [0, 1, 2].map((k) => a[k] + (b[k] - a[k]) * d);
};
const smooth = (e0, e1, x) => { const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };
// 발산 색: 작은 편차는 투명하게 두어 중심이 드러나게 한다
const divFn = (vmax, alpha, floor = 0.12) => (v) => {
  if (!Number.isFinite(v)) return null;
  const t = Math.max(-1, Math.min(1, v / vmax)), [r, g, b] = V.divColor(t);
  return [r / 255, g / 255, b / 255, alpha * smooth(floor, floor + 0.45, Math.abs(t))];
};
const jetFn = (v) => {
  if (!Number.isFinite(v)) return null;
  const [r, g, b] = seqColor((v - JET_MIN) / (JET_TOP - JET_MIN));
  return [r, g, b, 0.88 * smooth(JET_MIN - 4, JET_MIN, v)];
};
const cssHex = (c) => "#" + c.map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("");

// ---------------------------------------------------------------- 격자 도구
let F = {};
const has = (name) => !!F[name];
const cache = new Map();
// 그날 판을 f배 촘촘하게 (결과는 날짜·배수별로 저장)
function fine(name, target = 1.5) {
  const G = F[name], f = Math.max(1, Math.round(G.dlat / target)), key = `${name}:${T}:${f}`;
  if (!cache.has(key)) { if (cache.size > 400) cache.clear(); cache.set(key, refine(V.slice(G, T), f)); }
  return cache.get(key);
}
const isWrap = (G) => Math.abs(G.nlon * G.dlon - 360) < 1e-3;
function refine(G, f) {
  const wrap = isWrap(G), W = G.nlon, A = G.a;
  const nl = (G.nlat - 1) * f + 1, nm = wrap ? W * f : (W - 1) * f + 1;
  const at = (i, j) => {
    i = Math.max(0, Math.min(G.nlat - 1, i));
    j = wrap ? ((j % W) + W) % W : Math.max(0, Math.min(W - 1, j));
    return A[i * W + j];
  };
  const cr = (p0, p1, p2, p3, t) => 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t);
  const out = new Float32Array(nl * nm), row = new Array(4), q = new Array(4);
  for (let I = 0; I < nl; I++) {
    const fi = I / f, i = Math.min(Math.floor(fi), G.nlat - 2), di = fi - i;
    for (let J = 0; J < nm; J++) {
      const fj = J / f, j = Math.min(Math.floor(fj), wrap ? W - 1 : W - 2), dj = fj - j;
      let ok = true;
      for (let a = 0; a < 4 && ok; a++) {
        for (let b = 0; b < 4; b++) { q[b] = at(i + a - 1, j + b - 1); if (Number.isNaN(q[b])) { ok = false; break; } }
        if (ok) row[a] = cr(q[0], q[1], q[2], q[3], dj);
      }
      let v;
      if (ok) v = cr(row[0], row[1], row[2], row[3], di);
      else {   // 결측 주변: 있는 값만으로 선형 보간
        const c = [[at(i, j), (1 - di) * (1 - dj)], [at(i, j + 1), (1 - di) * dj], [at(i + 1, j), di * (1 - dj)], [at(i + 1, j + 1), di * dj]];
        let s = 0, w = 0; for (const [x, ww] of c) if (!Number.isNaN(x)) { s += x * ww; w += ww; }
        v = w > 0.5 ? s / w : NaN;
      }
      out[I * nm + J] = v;
    }
  }
  return { lat0: G.lat0, dlat: G.dlat / f, nlat: nl, lon0: G.lon0, dlon: G.dlon / f, nlon: nm, a: out };
}
const map2 = (A, B, fn) => { const a = new Float32Array(A.a.length); for (let k = 0; k < a.length; k++) a[k] = fn(A.a[k], B ? B.a[k] : 0); return { ...A, a }; };
const ser = (k) => (D.series[k] ? D.series[k][T] : NaN);
const dateOf = (i) => new Date(new Date(D.start + "T00:00:00Z").getTime() + i * 864e5).toISOString().slice(0, 10);
const gval = (G, i, j) => G.a[i * G.nlon + j];

// 위경도 격자를 구면 껍질로. colorFn(v) -> [r,g,b,a] 또는 null(그리지 않음)
function shell(G, r, colorFn) {
  const wrap = isWrap(G), nm = G.nlon + (wrap ? 1 : 0), nl = G.nlat;
  const pos = new Float32Array(nl * nm * 3), colr = new Float32Array(nl * nm * 4), on = new Uint8Array(nl * nm), idx = [];
  for (let i = 0; i < nl; i++) for (let j = 0; j < nm; j++) {
    const k = i * nm + j, p = xyz(G.lat0 + i * G.dlat, G.lon0 + j * G.dlon, r);
    pos[k * 3] = p.x; pos[k * 3 + 1] = p.y; pos[k * 3 + 2] = p.z;
    const c = colorFn(G.a[i * G.nlon + (j % G.nlon)]);
    if (c) { colr.set(c, k * 4); on[k] = c[3] > 0.01 ? 1 : 0; }
  }
  for (let i = 0; i < nl - 1; i++) for (let j = 0; j < nm - 1; j++) {
    const a = i * nm + j, b = a + 1, c = a + nm, d = c + 1;
    if (on[a] || on[b] || on[c] || on[d]) idx.push(a, c, b, b, c, d);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colr, 4));
  geo.setIndex(idx);
  return new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
}

// 마칭 스퀘어 등치선 (경도 순환)
function contour(G, level) {
  const segs = [], W = G.nlon, wrap = isWrap(G), A = G.a;
  const v = (i, j) => A[i * W + (j % W)];
  for (let i = 0; i < G.nlat - 1; i++) for (let j = 0; j < (wrap ? W : W - 1); j++) {
    const q = [v(i, j), v(i, j + 1), v(i + 1, j + 1), v(i + 1, j)];
    if (q.some((x) => !Number.isFinite(x))) continue;
    const c = [[i, j], [i, j + 1], [i + 1, j + 1], [i + 1, j]];
    const pts = [];
    for (let e = 0; e < 4; e++) {
      const a = q[e], b = q[(e + 1) % 4];
      if ((a < level) !== (b < level)) {
        const f = (level - a) / (b - a), p0 = c[e], p1 = c[(e + 1) % 4];
        pts.push([G.lat0 + (p0[0] + f * (p1[0] - p0[0])) * G.dlat, G.lon0 + (p0[1] + f * (p1[1] - p0[1])) * G.dlon]);
      }
    }
    if (pts.length === 2) segs.push(pts);
    else if (pts.length === 4) segs.push([pts[0], pts[1]], [pts[2], pts[3]]);
  }
  return segs;
}
// 가는 등치선: 선분 묶음 하나로
function thinLines(segs, r, color, opacity = 0.9) {
  const pos = new Float32Array(segs.length * 6);
  segs.forEach(([a, b], k) => { const p = xyz(a[0], a[1], r), q = xyz(b[0], b[1], r); pos.set([p.x, p.y, p.z, q.x, q.y, q.z], k * 6); });
  const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }));
}
// 굵은 등치선: 선분을 이어 선으로 만든 뒤 관(tube)으로
function chain(segs) {
  const key = (p) => `${p[0].toFixed(3)},${(((p[1] % 360) + 360) % 360).toFixed(3)}`;
  const ends = new Map(), used = new Uint8Array(segs.length), lines = [];
  segs.forEach((s, k) => { for (const p of s) { const kk = key(p); if (!ends.has(kk)) ends.set(kk, []); ends.get(kk).push(k); } });
  const next = (p) => { for (const k of ends.get(key(p)) || []) if (!used[k]) return k; return -1; };
  for (let s = 0; s < segs.length; s++) {
    if (used[s]) continue;
    used[s] = 1; const line = [segs[s][0], segs[s][1]];
    for (const dir of [1, -1]) {
      for (;;) {
        const tip = dir > 0 ? line[line.length - 1] : line[0], k = next(tip);
        if (k < 0) break;
        used[k] = 1; const [a, b] = segs[k], o = key(a) === key(tip) ? b : a;
        dir > 0 ? line.push(o) : line.unshift(o);
      }
    }
    lines.push(line);
  }
  return lines;
}
// 가는 점선: 이어 붙인 선을 dash개 점마다 긋고 gap개 점만큼 비운다 (점 간격은 대략 격자 1.5°)
function thinDashed(segs, r, color, dash = 3, gap = 2) {
  const pos = [];
  for (const line of chain(segs)) {
    for (let i = 0; i < line.length - 1; i += dash + gap)
      for (let j = i; j < Math.min(i + dash, line.length - 1); j++) {
        const p = xyz(line[j][0], line[j][1], r), q = xyz(line[j + 1][0], line[j + 1][1], r);
        pos.push(p.x, p.y, p.z, q.x, q.y, q.z);
      }
  }
  const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
  return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color }));
}
function tubes(segs, r, radius, color, opacity = 1) {
  const g = new THREE.Group(), mat = new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity });
  for (const line of chain(segs)) {
    if (line.length < 3) continue;
    const pts = line.map((p) => xyz(p[0], p[1], r));
    g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), Math.min(pts.length * 2, 600), radius, 5, false), mat));
  }
  return g;
}
function arrow(from, to, mat, width) {
  const g = new THREE.Group(), dir = new THREE.Vector3().subVectors(to, from), len = dir.length();
  if (len < 1e-4) return g;
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  const shaft = new THREE.Mesh(CYL, mat), head = new THREE.Mesh(CONE, mat);
  shaft.scale.set(width, len * 0.66, width); head.scale.set(width * 2.8, len * 0.34, width * 2.8);
  shaft.quaternion.copy(q); head.quaternion.copy(q);
  shaft.position.copy(from).addScaledVector(dir, 0.33); head.position.copy(from).addScaledVector(dir, 0.83);
  g.add(shaft, head); return g;
}
// 위경도 (lat, lon)에서 동쪽 성분 e, 북쪽 성분 n 방향으로 L도 만큼 가는 화살표
function vecArrow(lat, lon, e, n, L, r, mat, width) {
  const m = Math.hypot(e, n); if (!m) return new THREE.Group();
  const dl = n / m * L, dn = e / m * L / Math.max(Math.cos(lat * D2R), 0.2);
  return arrow(xyz(lat, lon, r), xyz(lat + dl, lon + dn, r), mat, width);
}
function label(text, pos, group, color, cls) {
  const el = document.createElement("div"); el.className = "lbl" + (cls ? " " + cls : ""); el.textContent = text; if (color) el.style.color = color;
  stage.appendChild(el); labels.push({ el, pos, group }); return el;
}
function clear(g) {
  while (g.children.length) {
    const c = g.children.pop();
    c.traverse((o) => { if (o.geometry && !SHARED.has(o.geometry)) o.geometry.dispose(); if (o.material) o.material.dispose(); });
  }
}
// 격자에서 국지 최대·최소 찾기 (|값| ≥ thr, 서로 sep도 이상 떨어진 것)
function extrema(G, thr, sep, nmax) {
  const W = G.nlon, wrap = isWrap(G), out = [];
  for (let i = 1; i < G.nlat - 1; i++) for (let j = 0; j < W; j++) {
    if (!wrap && (j === 0 || j === W - 1)) continue;
    const v = gval(G, i, j); if (!Number.isFinite(v) || Math.abs(v) < thr) continue;
    let ext = true;
    for (let a = -2; a <= 2 && ext; a++) for (let b = -2; b <= 2; b++) {
      if (!a && !b) continue; const ii = i + a; if (ii < 0 || ii >= G.nlat) continue;
      const w = gval(G, ii, ((j + b) % W + W) % W);
      if (Number.isFinite(w) && (v > 0 ? w > v : w < v)) { ext = false; break; }
    }
    if (ext) out.push({ lat: G.lat0 + i * G.dlat, lon: G.lon0 + j * G.dlon, v });
  }
  out.sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
  const keep = [];
  const dist = (p, q) => Math.acos(Math.min(1, Math.sin(p.lat * D2R) * Math.sin(q.lat * D2R) + Math.cos(p.lat * D2R) * Math.cos(q.lat * D2R) * Math.cos((p.lon - q.lon) * D2R))) / D2R;
  for (const p of out) { if (keep.every((q) => dist(p, q) > sep)) keep.push(p); if (keep.length >= nmax) break; }
  return keep;
}
const fmtLL = (p) => { const lo = Math.round(((p.lon + 180) % 360 + 360) % 360 - 180); return `${Math.round(p.lat)}°N ${Math.abs(lo)}°${lo >= 0 ? "E" : "W"}`; };

// ---------------------------------------------------------------- 그날의 층
const today = {};   // 요약에 쓰는 그날 값
function draw() {
  for (const k of LAYERS) clear(groups[k]);
  for (const l of labels) l.el.remove(); labels.length = 0;
  const dark = V.isDark(), ink = dark ? 0xf0f0f0 : 0x191919;
  const warm = dark ? "#eb6263" : "#c8393a", cool = dark ? "#4f9bf0" : "#2370cd";
  drawStrat(dark, ink, warm, cool);
  drawJet(dark, ink);
  drawMid(dark, ink, warm, cool);
  drawSfc(dark, ink, warm, cool);
  drawColumn();
  layerTags();
  hud();
}

// --- 성층권 10 hPa: 기온 편차(면), 고도 등치선(극소용돌이 모양), 가장자리(굵은 선), 중심, 60°N 동서풍 고리
function drawStrat(dark, ink, warm, cool) {
  const z10 = fine("z10", 2.25), edge = D.z10_edge[T];
  if (has("t10_anom")) groups.strat.add(shell(fine("t10_anom", 2.25), R.strat, divFn(20, 0.8, 0.1)));
  else groups.strat.add(shell(map2(z10, null, (v) => Math.min(v - edge, 0)), R.strat, divFn(1500, 0.45, 0.05)));   // 기온장이 없으면 소용돌이 안쪽만
  // 고도 등치선 600 m 간격 (가장자리 고도 기준)
  const segs = [];
  for (let L = edge - 3000; L <= edge + 1800; L += 600) if (L !== edge) segs.push(...contour(z10, L));
  groups.strat.add(thinLines(segs, R.strat + 0.001, dark ? 0xb9c3cc : 0x4a5560, 0.55));
  groups.strat.add(tubes(contour(z10, edge), R.strat + 0.002, 0.0042, dark ? 0x9dc8f7 : 0x1757ac));
  const vlat = ser("vortex_lat"), vlon = ser("vortex_lon"), pieces = ser("vortex_pieces");
  if (Number.isFinite(vlat)) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.02, 16, 12), new THREE.MeshBasicMaterial({ color: dark ? 0x9dc8f7 : 0x0e3d7e }));
    m.position.copy(xyz(vlat, vlon, R.strat)); groups.strat.add(m);
    label(pieces >= 2 ? "극소용돌이 (분리)" : "극소용돌이 중심", xyz(vlat, vlon, R.strat + 0.05), "strat", cool);
  }
  // 승온은 그날 10 hPa 기온 편차장이 있는 곳에만 그린다. 극관 평균값으로 극 둘레에 원을 그리지 않는다(실제 분포가 아니므로).
  if (has("t10_anom")) {
    // 실제 승온·냉각 중심: 편차 ±8 K 이상인 국지 극값, 서로 35° 이상 떨어진 것 최대 3개
    for (const p of extrema(V.slice(F.t10_anom, T), 8, 35, 3))
      label(`${p.v > 0 ? "승온 +" : "냉각 −"}${Math.abs(p.v).toFixed(0)} K`, xyz(p.lat, p.lon, R.strat + 0.04), "strat", p.v > 0 ? warm : cool, "sm");
  }
  const t10 = ser("t10_cap_anom");
  if (Number.isFinite(t10) && Math.abs(t10) >= 3)
    label(`극관(60~90°N) 평균 ${V.sgn(t10, 0, " K")}`, new THREE.Vector3(0, R.strat + 0.09, 0), "strat", t10 > 0 ? warm : cool, "sm");
  const u = ser("u1060"), ring = [];
  for (let lo = 0; lo <= 360; lo += 4) ring.push(xyz(60, lo, R.strat + 0.003));
  const ringCol = u >= 0 ? (dark ? 0x338ced : 0x257de0) : (dark ? 0xeb6263 : 0xc8393a);
  groups.strat.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(ring, true), 90, 0.003 + Math.min(Math.abs(u), 60) / 60 * 0.01, 6, true),
    new THREE.MeshBasicMaterial({ color: ringCol, transparent: true, opacity: 0.7 })));
  label(`60°N ${u >= 0 ? "서풍" : "동풍"} ${Math.abs(u).toFixed(0)} m/s`, xyz(60, 0, R.strat + 0.04), "strat", u >= 0 ? cool : warm);
}

// --- 250 hPa 제트: 풍속 50 m/s 이상 영역(면)과 50 m/s 등치선(굵은 선), 70 m/s(가는 선), 축의 흐름 방향 화살표
function drawJet(dark, ink) {
  const U = fine("u250"), Vv = has("v250") ? fine("v250") : null;
  const S = map2(U, Vv, (u, v) => Math.hypot(u, v));
  groups.jet.add(shell(S, R.jet, jetFn));
  const edgeCol = dark ? 0xffb35c : 0xd9480f;
  groups.jet.add(tubes(contour(S, JET_MIN), R.jet + 0.002, 0.0032, edgeCol));
  groups.jet.add(thinLines(contour(S, 70), R.jet + 0.002, dark ? 0xf3d9fa : 0x6a1b7c, 0.9));
  // 축: 경도 10°마다 15~75°N에서 풍속이 가장 센 곳, 그 바람 방향으로 화살표
  const mat = new THREE.MeshBasicMaterial({ color: dark ? 0xffffff : 0x3b1a4a });
  let top = { v: -1 };
  for (let lon = 0; lon < 360; lon += 10) {
    const j = Math.round((lon - S.lon0) / S.dlon); if (j < 0 || j >= S.nlon) continue;
    let best = -1, bi = -1;
    for (let i = 0; i < S.nlat; i++) { const la = S.lat0 + i * S.dlat; if (la < 15 || la > 75) continue; const v = gval(S, i, j); if (v > best) { best = v; bi = i; } }
    if (best < JET_MIN) continue;
    const la = S.lat0 + bi * S.dlat, u = gval(U, bi, j), v = Vv ? gval(Vv, bi, j) : 0;
    groups.jet.add(vecArrow(la, lon, u, v, 5 + (best - JET_MIN) / 8, R.jet + 0.006, mat, 0.0032));
    if (best > top.v) top = { v: best, lat: la, lon };
  }
  today.jet = top.v > 0 ? top : null;
  if (today.jet) label(`제트 최대 ${top.v.toFixed(0)} m/s`, xyz(top.lat + 4, top.lon, R.jet + 0.04), "jet", dark ? "#ffc46b" : "#a8235a");
}

// --- 500 hPa: 고도 편차(면), 파동활동 플럭스(화살표), 블로킹
function drawMid(dark, ink, warm, cool) {
  const Z = fine("z500_anom");
  groups.mid.add(shell(Z, R.mid, divFn(240, 0.8, 0.15)));
  // 편차 중심 표시 (±120 m 이상, 30° 이상 떨어진 것 최대 6개)
  const ex = extrema(Z, 120, 30, 6);
  for (const p of ex) label(`${p.v > 0 ? "+" : "−"}${Math.abs(p.v).toFixed(0)}`, xyz(p.lat, p.lon, R.mid + 0.02), "mid", p.v > 0 ? warm : cool, "sm");
  today.z500 = ex;
  // 파동활동 플럭스: 상위 35%만, 길이는 세기에 비례
  const fx = V.slice(F.waf_fx, T), fy = V.slice(F.waf_fy, T), mags = [];
  for (let k = 0; k < fx.a.length; k++) if (Number.isFinite(fx.a[k]) && Number.isFinite(fy.a[k])) mags.push(Math.hypot(fx.a[k], fy.a[k]));
  mags.sort((a, b) => a - b);
  const ref = mags[Math.floor(mags.length * 0.95)] || 1, thr = mags[Math.floor(mags.length * 0.65)] || 0;
  const mat = new THREE.MeshBasicMaterial({ color: ink });
  for (let i = 0; i < fx.nlat; i++) for (let j = 0; j < fx.nlon; j++) {
    const k = i * fx.nlon + j, a = fx.a[k], b = fy.a[k]; if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
    const m = Math.hypot(a, b); if (m < thr) continue;
    groups.mid.add(vecArrow(fx.lat0 + i * fx.dlat, fx.lon0 + j * fx.dlon, a, b, 3 + Math.min(m / ref, 1.3) * 7, R.mid + 0.008, mat, 0.0034));
  }
  if (ser("blocked") >= 1) label(`우랄 블로킹 (Z500 ${V.sgn(ser("ural"), 0, " m")})`, xyz(66, 60, R.mid + 0.06), "mid", warm);
}

// --- 지상·해양: 면은 고른 변수의 편차, 선은 해면기압 편차 등치선과 고·저기압 중심, 해빙·눈덮임 경계
// 해빙·눈덮임·토양수분은 '줄면 빨강(따뜻한 쪽), 늘면 파랑'이 되게 부호를 뒤집어 칠한다.
const SFC_VARS = {
  t: { name: "기온 (육지 2 m 기온 + 해수면온도)", need: ["t2m_anom", "sst_anom"], range: "육지 ±8 °C · 바다 ±2.5 °C" },
  skt: { name: "지표기온 (skin temperature)", need: ["skt_anom"], range: "±8 °C", vmax: 8 },
  ci: { name: "해빙 농도", need: ["ci", "ci_clim"], range: "±40 %p (줄면 빨강)", vmax: 0.4, flip: true },
  snow: { name: "눈덮임 비율", need: ["snowc", "snowc_clim"], range: "±60 %p (줄면 빨강)", vmax: 0.6, flip: true },
  swvl1: { name: "토양수분 (표층 0~7 cm)", need: ["swvl1_anom"], range: "±0.08 m³/m³ (마르면 빨강)", vmax: 0.08, flip: true },
};
let sfcVar = "t";
const sfcOK = (k) => SFC_VARS[k].need.every(has);
function sfcField(k) {
  if (k === "ci" || k === "snow") { const a = k === "ci" ? "ci" : "snowc"; return map2(fine(a), fine(a + "_clim"), (x, c) => x - c); }
  return fine(k + "_anom");
}
function drawSfc(dark, ink, warm, cool) {
  if (sfcVar === "t") {
    if (has("sst_anom")) groups.sfc.add(shell(fine("sst_anom"), R.sfc + 0.001, divFn(2.5, 0.85, 0.12)));
    if (has("t2m_anom")) groups.sfc.add(shell(fine("t2m_anom"), R.sfc + 0.002, divFn(8, 0.85, 0.1)));
  } else if (sfcOK(sfcVar)) {
    const s = SFC_VARS[sfcVar], fn = divFn(s.vmax, 0.88, 0.1);
    groups.sfc.add(shell(sfcField(sfcVar), R.sfc + 0.002, s.flip ? (v) => fn(-v) : fn));
  }
  if (has("msl_anom")) {
    // 해면기압 편차 등치선은 면을 가리므로 기본으로 끄고, 켜면 ±8 hPa부터 8 hPa 간격의 가는 선으로 그린다
    if ($("mslChk").checked) {
      const M = fine("msl_anom"), hi = [], lo = [];
      for (let L = 8; L <= 32; L += 8) { hi.push(...contour(M, L)); lo.push(...contour(M, -L)); }
      // + 붉은 실선, − 파란 점선 (눈덮임 경계의 보라와 헷갈리지 않게 파랑은 분명한 파랑으로)
      groups.sfc.add(thinLines(hi, R.sfc + 0.004, dark ? 0xff6b6b : 0xc81e1e, 1));
      groups.sfc.add(thinDashed(lo, R.sfc + 0.004, dark ? 0x4dabf7 : 0x1565c0));
    }
    // 고기압·저기압 편차 중심(±8 hPa 이상, 서로 30° 이상 떨어진 것 최대 6개)은 늘 표시
    for (const p of extrema(V.slice(F.msl_anom, T), 8, 30, 6)) label(`${p.v > 0 ? "H" : "L"} ${V.sgn(p.v, 0)}`, xyz(p.lat, p.lon, R.sfc + 0.02), "sfc", p.v > 0 ? warm : cool, "sm");
  }
  if (has("ci")) {
    const ice = dark ? 0xe8f7ff : 0x0b7285;
    groups.sfc.add(tubes(contour(fine("ci"), 0.15), R.sfc + 0.005, 0.0028, ice));
    if (has("ci_clim")) groups.sfc.add(thinLines(contour(fine("ci_clim"), 0.15), R.sfc + 0.005, ice, 0.6));
  }
  if (has("snowc")) {
    const sn = dark ? 0xd0bfff : 0x5f3dc4;
    groups.sfc.add(tubes(contour(fine("snowc"), 0.5), R.sfc + 0.005, 0.0024, sn));
    if (has("snowc_clim")) groups.sfc.add(thinLines(contour(fine("snowc_clim"), 0.5), R.sfc + 0.005, sn, 0.6));
  }
  const kr = new THREE.Mesh(new THREE.SphereGeometry(0.008, 10, 8), new THREE.MeshBasicMaterial({ color: ink }));
  kr.position.copy(xyz(36.5, 127.5, R.sfc + 0.004)); groups.sfc.add(kr);
  label("한반도", xyz(36.5, 131, R.sfc + 0.03), "sfc", null, "sm");
  label(`Niño3.4 ${V.sgn(ser("nino34"), 2, "°C")}`, xyz(0, 205, R.sfc + 0.05), "sfc");
}

// --- 극관 기둥: 층별 극관 고도 표준화 편차
function drawColumn() {
  const P = D.pch, nl = P.levels.length;
  for (let l = 0; l < nl; l++) {
    const v = P.v[T * nl + l]; if (v === null) continue;
    const s = v * 0.1, p = P.levels[l];
    const h = R.sfc + (Math.log(1000) - Math.log(p)) / (Math.log(1000) - Math.log(10)) * (R.strat - R.sfc);
    const [r, g, b] = V.divColor(Math.max(-1, Math.min(1, s / 3)));
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.016, 24), new THREE.MeshBasicMaterial({ color: new THREE.Color(r / 255, g / 255, b / 255), transparent: true, opacity: 0.95 }));
    disc.position.set(0, h, 0); groups.col.add(disc);
    if ([10, 100, 500, 1000].includes(p)) label(`${p} hPa ${V.sgn(s, 1, "σ")}`, new THREE.Vector3(0.09, h, 0), "col", null, "sm");
  }
}

// --- 층 이름표: 북극 위 각 층 높이에 둔다 (극 쪽 연직축은 화면에서도 세로로 보여 층 순서가 그대로 읽힌다)
function layerTags() {
  const txt = { strat: "10 hPa 성층권 · 약 31 km", jet: "250 hPa 제트 · 약 10 km", mid: "500 hPa · 약 5.5 km", sfc: "지상·해양" };
  for (const k in txt) label(txt[k], new THREE.Vector3(0, R[k] + (k === "sfc" ? 0.01 : 0), 0), k, null, "tag");
}

function hud() {
  const d = dateOf(T), mk = D.marks.filter((m) => m.date === d).map((m) => m.label);
  const jet = today.jet ? `제트 최대 ${today.jet.v.toFixed(0)} m/s (${fmtLL(today.jet)})` : "제트 50 m/s 이상 없음";
  const zc = (today.z500 || []).slice(0, 2).map((p) => `${V.sgn(p.v, 0, " m")} (${fmtLL(p)})`).join(", ");
  $("hud").innerHTML = `<div class="d">${d}</div>` +
    `<b>10 hPa</b> 60°N 동서풍 ${V.fmt(ser("u1060"), 1)} m/s · 극관 기온 편차 ${V.sgn(ser("t10_cap_anom"), 1, " K")}<br>` +
    `<b>250 hPa</b> ${jet}<br>` +
    `<b>500 hPa</b> 큰 편차 ${zc || "없음"}${ser("blocked") >= 1 ? " · 우랄 블로킹" : ""}<br>` +
    `<b>지수</b> AO ${V.sgn(ser("ao"), 2)} · Niño3.4 ${V.sgn(ser("nino34"), 2, "°C")} · 한반도 기온 ${V.sgn(ser("korea_t"), 1, "°C")}` +
    (mk.length ? `<br><span class="ev">● ${mk.join(", ")}</span>` : "");
  $("slider").value = T;
  const [lo, hi] = range, inR = T >= lo && T <= hi;
  $("rangeInfo").textContent = `재생 구간 ${dateOf(lo)} ~ ${dateOf(hi)} (${hi - lo + 1}일) · 지금 ${d}` +
    (inR ? ` (${T - lo + 1}일째)` : " (구간 밖: 재생하면 구간 첫날부터)");
  playLabel();
}

// 재생: 구간 끝에 있거나 구간 밖이면 첫날부터, 아니면 지금 날짜부터 이어서
function playLabel() {
  const [lo, hi] = range;
  $("playBtn").textContent = playing ? "❚❚ 정지" : T >= hi || T < lo ? "▶ 첫날부터 재생" : "▶ 이어서 재생";
  $("playBtn").setAttribute("aria-pressed", playing);
}
function setPlay(on) {
  const [lo, hi] = range;
  if (on && (T >= hi || T < lo)) { T = lo; draw(); }
  playing = on; lastTick = performance.now(); playLabel();
}

// ---------------------------------------------------------------- 범례
function bar(fn, n = 40) {
  const stops = []; for (let k = 0; k <= n; k++) { const c = fn(k / n); stops.push(`${c} ${(k / n * 100).toFixed(1)}%`); }
  return `<span class="cbar" style="background:linear-gradient(90deg,${stops.join(",")})"></span>`;
}
const divBar = () => bar((x) => { const [r, g, b] = V.divColor(x * 2 - 1); return `rgb(${r},${g},${b})`; });
const jetBar = () => bar((x) => cssHex(seqColor(x)));
function keys() {
  const t10 = has("t10_anom");
  const rows = [
    ["성층권 10 hPa", divBar(), t10 ? "−20 ~ +20 K" : "−1500 ~ +1500 m",
      (t10 ? "면: 기온 편차(빨강 = 승온, 파랑 = 냉각). 숫자: ±8 K 넘는 승온·냉각 중심. "
        : "면: 극소용돌이 안쪽(가장자리보다 고도가 낮은 곳, 진할수록 깊음). 기온 편차 분포는 자료 준비 중이라 극관 평균값만 숫자로 보인다. ") +
      "가는 선: 고도 600 m 간격. <b>굵은 파란 선</b>: 극소용돌이 가장자리(그날 평년 60°N 평균 고도). 60°N 고리: 동서풍(빨강 = 동풍 역전)."],
    ["제트 250 hPa", jetBar(), `${JET_MIN} ~ ${JET_TOP}+ m/s`,
      `면: 풍속 ${JET_MIN} m/s 이상. <b>굵은 주황 선</b>: ${JET_MIN} m/s 등풍속선, 가는 보라 선: 70 m/s. 화살표: 경도 10°마다 제트 축의 바람 방향.`],
    ["500 hPa", divBar(), "−240 ~ +240 m",
      "면: 고도 편차(작은 편차는 투명, 빨강 + 파랑 −). 숫자: ±120 m 넘는 편차 중심(m). 검은 화살표: 7일 평균 파동활동 플럭스(Takaya-Nakamura, 상위 35%)."],
    ["지상·해양", divBar(), SFC_VARS[sfcVar].range,
      `면: ${SFC_VARS[sfcVar].name} 편차(1991~2020 평년 대비). H/L: 해면기압 편차 중심(±8 hPa 이상, hPa). ` +
        ($("mslChk").checked ? "가는 선: 해면기압 편차 8 hPa 간격(붉은 실선 +, 파란 점선 −). " : "") +
      (has("ci") ? "<b>청록 굵은 선</b>: 해빙 경계(농도 15%), 가는 선: 평년 경계. " : "") +
      (has("snowc") ? "<b>보라 굵은 선</b>: 눈덮임 경계(50%), 가는 선: 평년. " : "")],
    ["극관 기둥", divBar(), "−3 ~ +3 σ", "층별(1000~10 hPa) 극관 고도 표준화 편차. 위에서 아래로 번지면 하향 전파."],
  ];
  $("keys").innerHTML = rows.map(([n, b, rng, d]) => `<div class="krow"><div class="kh"><b>${n}</b>${b}<span class="small">${rng}</span></div><div class="small">${d}</div></div>`).join("");
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
$("resetBtn").onclick = () => Object.assign(cam, CAM0);

// 보일 층 고르기: 전체가 켜진 상태에서 층을 누르면 그 층만 남기고, 그 뒤로는 누를 때마다 더하거나 뺀다(여러 개 가능).
// '전체'는 모두 켠다.
const layerBtns = () => [...document.querySelectorAll("[data-l]")];
function showLayers() {
  let all = true;
  for (const b of layerBtns()) { const on = b.getAttribute("aria-pressed") === "true"; groups[b.dataset.l].visible = on; all &&= on; }
  $("allBtn").setAttribute("aria-pressed", all);
}
function toggleLayer(b) {
  if ($("allBtn").getAttribute("aria-pressed") === "true") {
    for (const x of layerBtns()) x.setAttribute("aria-pressed", x === b);
    return showLayers();
  }
  const on = b.getAttribute("aria-pressed") !== "true";
  if (!on && layerBtns().filter((x) => x.getAttribute("aria-pressed") === "true").length === 1) return;   // 하나는 남긴다
  b.setAttribute("aria-pressed", on); showLayers();
}
function showAll() { for (const b of layerBtns()) b.setAttribute("aria-pressed", true); showLayers(); }

const proj = new THREE.Vector3();
function loop(ts) {
  requestAnimationFrame(loop);
  if (playing && ts - lastTick > 1000 / +$("speedSel").value) {
    lastTick = ts; const [lo, hi] = range;
    if (T >= hi) { if ($("loopChk").checked) T = lo; else setPlay(false); }   // 끝나면 멈춘다(반복을 켜면 첫날로)
    else T = T < lo ? lo : T + 1;
    draw();
  }
  place(); renderer.render(scene, camera);
  const w = stage.clientWidth, h = stage.clientHeight, camDir = camera.position.clone().normalize();
  for (const l of labels) {
    if (!groups[l.group].visible) { l.el.style.display = "none"; continue; }
    proj.copy(l.pos).project(camera);
    const behind = l.pos.clone().normalize().dot(camDir) < -0.05 && l.pos.length() < 1.4 && l.group !== "col";
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
  // 재생 구간 목록: (대시보드에서 넘어온 기간) · 전체 자료 · 최근 30일 · 최근 7일
  const ranges = [];
  if (q.get("start") && q.get("end")) {
    const a = Math.max(0, idx(q.get("start"))), b = Math.min(D.n - 1, idx(q.get("end")));
    if (b >= a && b >= 0) ranges.push({ t: `대시보드 기간 ${dateOf(a)} ~ ${dateOf(b)}`, r: [a, b] });
  }
  ranges.push({ t: `전체 자료 ${D.start} ~ ${D.end} (${D.n}일)`, r: [0, D.n - 1] });
  for (const n of [30, 7]) if (D.n > n) ranges.push({ t: `최근 ${n}일 ${dateOf(D.n - n)} ~ ${D.end}`, r: [D.n - n, D.n - 1] });
  range = ranges[0].r; T = range[1];   // 처음 화면은 구간 마지막 날, 재생은 구간 첫날부터
  $("rangeSel").innerHTML = ranges.map((o, i) => `<option value="${i}">재생 구간: ${o.t}</option>`).join("");
  $("rangeSel").onchange = (e) => { range = ranges[+e.target.value].r; playing = false; T = range[0]; draw(); };
  const tk = $("ticks"), pct = (i) => (i / (D.n - 1)) * 100 + "%";
  for (const m of D.marks) { const i = idx(m.date); if (i < 0 || i >= D.n) continue; const s = document.createElement("span"); s.className = m.kind; s.style.left = pct(i); s.textContent = m.kind === "ssw" ? "SSW" : "블로킹"; s.title = `${m.date} ${m.label}`; tk.appendChild(s); }
  $("slider").oninput = (e) => { T = +e.target.value; draw(); };
  $("playBtn").onclick = () => setPlay(!playing);
  $("firstBtn").onclick = () => { setPlay(false); T = range[0]; draw(); };
  $("lastBtn").onclick = () => { setPlay(false); T = range[1]; draw(); };
  const jump = (s) => { T = Math.max(0, Math.min(D.n - 1, T + s * +$("jumpSel").value)); draw(); };
  $("backBtn").onclick = () => jump(-1); $("fwdBtn").onclick = () => jump(1);
  for (const b of layerBtns()) b.onclick = () => toggleLayer(b);
  $("allBtn").onclick = showAll;
  $("gapSel").onchange = (e) => { gap = +e.target.value; setR(); draw(); };
  const sel = $("sfcSel");
  sel.innerHTML = Object.entries(SFC_VARS).map(([k, s]) => `<option value="${k}"${sfcOK(k) || k === "t" ? "" : " disabled"}>지상: ${s.name.split(" (")[0]}${sfcOK(k) || k === "t" ? "" : " (자료 준비 중)"}</option>`).join("");
  sel.onchange = (e) => { sfcVar = e.target.value; draw(); keys(); };
  $("mslChk").onchange = () => { draw(); keys(); };
  const missing = ["t10_anom", "v250", "t2m(북반구)", "ci", "snowc", "swvl1_anom", "skt_anom"].filter((k) => k === "t2m(북반구)" ? !(has("t2m_anom") && F.t2m_anom.lat0 < 10) : !has(k));
  $("notes").textContent = `자료 ${D.start} ~ ${D.end}. 높이는 과장했다(10 hPa 약 31 km를 지구 반지름의 0.32배로). 격자는 3차 보간으로 부드럽게 그렸다.` +
    (missing.length ? ` 이번 자료에 없는 항목: ${missing.join(", ")} (다음 갱신에 추가).` : "");
  setTheme(document.documentElement.dataset.theme || "");
  addEventListener("resize", resize); resize(); draw(); keys(); requestAnimationFrame(loop);
})();
})();
