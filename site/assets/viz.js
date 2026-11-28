// 공통 시각화 도구: 격자 해독, 발산 색표, 극투영·위경도 지도(canvas), 선·막대 그림(SVG).
// 외부 라이브러리 없이 동작한다.
"use strict";

const V = {};

V.css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
V.isDark = () => getComputedStyle(document.documentElement).colorScheme.includes("dark");

// ---------------------------------------------------------------- 격자
// v: 정수 목록(null = 결측) 또는 b64: int8/int16 리틀엔디언 묶음(가장 작은 정수 = 결측, src/export.py의 _pack)
V.decode = (g) => {
  const off = g.offset || 0;
  if (g.b64) {
    const bin = atob(g.b64), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const q = g.dtype === "i1" ? new Int8Array(u8.buffer) : new Int16Array(u8.buffer), fill = g.dtype === "i1" ? -128 : -32768;
    const a = new Float32Array(q.length);
    for (let i = 0; i < q.length; i++) a[i] = q[i] === fill ? NaN : q[i] * g.scale + off;
    return { lat0: g.lat0, dlat: g.dlat, nlat: g.nlat, lon0: g.lon0, dlon: g.dlon, nlon: g.nlon, a };
  }
  const n = g.v.length, a = new Float32Array(n);
  for (let i = 0; i < n; i++) a[i] = g.v[i] === null ? NaN : g.v[i] * g.scale + off;
  return { lat0: g.lat0, dlat: g.dlat, nlat: g.nlat, lon0: g.lon0, dlon: g.dlon, nlon: g.nlon, a };
};
// 2차원(또는 시간 x 위도 x 경도) 격자에서 t번째 판을 꺼낸다
V.slice = (G, t) => ({ ...G, a: G.a.subarray(t * G.nlat * G.nlon, (t + 1) * G.nlat * G.nlon) });
V.sample = (G, lat, lon, wrap = true) => {
  const fi = (lat - G.lat0) / G.dlat;
  let fj = (lon - G.lon0) / G.dlon;
  if (wrap) { const span = G.nlon; fj = ((fj % span) + span) % span; }
  const i0 = Math.floor(fi), j0 = Math.floor(fj);
  if (i0 < 0 || i0 > G.nlat - 1 || (!wrap && (j0 < 0 || j0 > G.nlon - 1))) return NaN;
  const i1 = Math.min(i0 + 1, G.nlat - 1), j1 = wrap ? (j0 + 1) % G.nlon : Math.min(j0 + 1, G.nlon - 1);
  const di = fi - i0, dj = fj - j0, A = G.a, W = G.nlon;
  const v00 = A[i0 * W + j0], v01 = A[i0 * W + j1], v10 = A[i1 * W + j0], v11 = A[i1 * W + j1];
  const vals = [[v00, (1 - di) * (1 - dj)], [v01, (1 - di) * dj], [v10, di * (1 - dj)], [v11, di * dj]];
  let s = 0, w = 0;
  for (const [v, ww] of vals) if (!Number.isNaN(v)) { s += v * ww; w += ww; }
  return w > 0.3 ? s / w : NaN;
};

// ---------------------------------------------------------------- 색
const DIV_LIGHT = ["#0e3d7e", "#2370cd", "#6aabf1", "#b6d5f8", "#efefef", "#f8cfc4", "#ee8a70", "#dc3c3d", "#8c1c1d"];
const DIV_DARK = ["#9dc8f7", "#519ced", "#2370cd", "#173f73", "#383838", "#6e2a26", "#b8433a", "#e76a5d", "#f6b7a8"];
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
V.divColor = (t, reverse = false) => {      // t: -1 ~ 1
  const pal = V.isDark() ? DIV_DARK : DIV_LIGHT;
  let x = Math.max(-1, Math.min(1, reverse ? -t : t));
  const f = (x + 1) / 2 * (pal.length - 1), i = Math.min(Math.floor(f), pal.length - 2), d = f - i;
  const a = hex(pal[i]), b = hex(pal[i + 1]);
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * d));
};
// 강수 색표: 적음(−) 갈색, 많음(+) 녹색, 가운데 무채색. 모식도와 대시보드가 함께 쓴다.
// 양쪽 대표색(밝은 #a6611a·#18a070, 어두운 #b97f30·#2ea877)은 적록 색각 이상 모의에서도 구분된다(OKLab ΔE 9.7, 8.2)
const WETDRY_LIGHT = ["#5a3306", "#a6611a", "#cf9a52", "#ecd3a6", "#efefef", "#b3e3cd", "#5cc09a", "#18a070", "#0a5c3e"];
const WETDRY_DARK = ["#f0cf96", "#d9a253", "#b97f30", "#5e4420", "#383838", "#1c5440", "#2ea877", "#4cc492", "#a5ecc8"];
V.wetDry = (t) => {      // t: -1(적음) ~ 1(많음) -> [r, g, b] 0~255
  const pal = V.isDark() ? WETDRY_DARK : WETDRY_LIGHT;
  const f = (Math.max(-1, Math.min(1, t)) + 1) / 2 * (pal.length - 1), i = Math.min(Math.floor(f), pal.length - 2), d = f - i;
  const a = hex(pal[i]), b = hex(pal[i + 1]);
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * d));
};
// 값 범위에 맞춰 0을 가운데 둔 대칭 한계를 고른다 (99.5 백분위)
V.niceMax = (arr) => {
  const v = Array.from(arr).filter((x) => Number.isFinite(x)).map(Math.abs).sort((a, b) => a - b);
  if (!v.length) return 1;
  const m = v[Math.floor(0.995 * (v.length - 1))] || v[v.length - 1] || 1;
  const p = Math.pow(10, Math.floor(Math.log10(m)));
  for (const s of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (s * p >= m) return s * p;
  return 10 * p;
};
V.legend = (el, vmax, unit, reverse = false, steps = 9, colorOf = null) => {
  el.innerHTML = "";
  const c = document.createElement("canvas"); c.width = 220; c.height = 12;
  const ctx = c.getContext("2d");
  for (let x = 0; x < 220; x++) {
    const t = Math.round(((x / 219) * 2 - 1) * (steps - 1) / 2) / ((steps - 1) / 2);
    const [r, g, b] = colorOf ? colorOf(t) : V.divColor(t, reverse); ctx.fillStyle = `rgb(${r},${g},${b})`; ctx.fillRect(x, 0, 1, 12);
  }
  const lo = document.createElement("span"), hi = document.createElement("span");
  lo.textContent = `−${V.fmt(vmax)}`; hi.textContent = `+${V.fmt(vmax)} ${unit}`;
  el.append(lo, c, hi);
};
V.fmt = (v, nd) => {
  if (!Number.isFinite(v)) return "–";
  if (nd === undefined) nd = Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
  return v.toFixed(nd);
};
V.sgn = (v, nd = 1, unit = "") => (Number.isFinite(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(nd) + unit : "–");
V.cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");

// ---------------------------------------------------------------- 지도
// 북극 투영 (정각 극평사도법). 중심 경도 rot가 화면 아래쪽을 향한다.
V.polar = (latMin = 15, rot = 120) => {
  const R = (lat) => Math.tan((90 - lat) * Math.PI / 360);
  const rmax = R(latMin);
  return {
    fwd(lat, lon, size) {
      const r = R(lat) / rmax * size / 2, th = (lon - rot) * Math.PI / 180;
      return [size / 2 + r * Math.sin(th), size / 2 + r * Math.cos(th)];
    },
    inv(x, y, size) {
      const dx = x - size / 2, dy = y - size / 2, r = Math.hypot(dx, dy) / (size / 2) * rmax;
      if (r > rmax) return null;
      const lat = 90 - Math.atan(r) * 360 / Math.PI;
      const lon = (Math.atan2(dx, dy) * 180 / Math.PI + rot + 360) % 360;
      return [lat, lon];
    },
    circle: true,
  };
};
V.rect = (box) => {   // box = [남, 북, 서, 동]
  const [s, n, w, e] = box;
  return {
    fwd(lat, lon, W, H) { return [(lon - w) / (e - w) * W, (n - lat) / (n - s) * H]; },
    inv(x, y, W, H) { return [n - y / H * (n - s), w + x / W * (e - w)]; },
    aspect: (n - s) / (e - w) / Math.cos((n + s) / 2 * Math.PI / 180),
  };
};

V.drawMap = (canvas, opt) => {
  // opt: {grid, proj, vmax, reverse, colorOf(색표 함수, 기본 V.divColor), coast, arrows, unit, box, wrap, label, marker}
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || 360;
  const W = Math.round(cssW * dpr), H = Math.round((opt.proj.circle ? cssW : cssW * opt.proj.aspect) * dpr);
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(W, H), px = img.data;
  const step = 2;   // 2픽셀마다 계산해 속도를 맞춘다
  const bg = hex(V.isDark() ? "#1c1c1c" : "#ffffff");
  for (let y = 0; y < H; y += step) for (let x = 0; x < W; x += step) {
    const ll = opt.proj.circle ? opt.proj.inv(x, y, W) : opt.proj.inv(x, y, W, H);
    let col = null;
    if (ll) {
      const v = V.sample(opt.grid, ll[0], ll[1], opt.wrap !== false);
      col = Number.isFinite(v) ? (opt.colorOf || V.divColor)(Math.round(v / opt.vmax * 4) / 4, opt.reverse) : (V.isDark() ? [44, 44, 44] : [230, 230, 228]);
    }
    for (let yy = y; yy < Math.min(y + step, H); yy++) for (let xx = x; xx < Math.min(x + step, W); xx++) {
      const k = (yy * W + xx) * 4, c = col || bg;
      px[k] = c[0]; px[k + 1] = c[1]; px[k + 2] = c[2]; px[k + 3] = col ? 255 : 0;
    }
  }
  ctx.putImageData(img, 0, 0);
  const P = (lat, lon) => (opt.proj.circle ? opt.proj.fwd(lat, lon, W) : opt.proj.fwd(lat, lon, W, H));
  // 위선·경선
  ctx.strokeStyle = V.isDark() ? "rgba(255,255,255,.18)" : "rgba(0,0,0,.14)"; ctx.lineWidth = dpr * 0.6;
  if (opt.proj.circle) {
    for (const la of [30, 60]) { ctx.beginPath(); for (let lo = 0; lo <= 360; lo += 3) { const [x, y] = P(la, lo); lo ? ctx.lineTo(x, y) : ctx.moveTo(x, y); } ctx.stroke(); }
    for (let lo = 0; lo < 360; lo += 60) { ctx.beginPath(); const [a, b] = P(90, lo), [c, d] = P(15, lo); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); }
  }
  // 해안선
  if (opt.coast) {
    ctx.strokeStyle = V.isDark() ? "rgba(235,235,235,.75)" : "rgba(40,40,40,.8)"; ctx.lineWidth = dpr * 0.8;
    for (const ln of opt.coast) {
      ctx.beginPath(); let pen = false, px0 = null;
      for (let i = 0; i < ln.length; i += 2) {
        const lon = ln[i], lat = ln[i + 1];
        if (opt.proj.circle && lat < 14) { pen = false; continue; }
        const [x, y] = P(lat, lon);
        if (pen && px0 && Math.abs(x - px0) > W / 2) pen = false;
        pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y); pen = true; px0 = x;
      }
      ctx.stroke();
    }
  }
  if (opt.boxes) {
    ctx.strokeStyle = V.isDark() ? "rgba(255,255,255,.6)" : "rgba(25,25,25,.55)"; ctx.lineWidth = dpr; ctx.setLineDash([4 * dpr, 3 * dpr]);
    for (const [s, n, w, e] of opt.boxes) {
      ctx.beginPath();
      const pts = [[s, w], [s, e], [n, e], [n, w], [s, w]];
      pts.forEach(([la, lo], i) => { const [x, y] = P(la, lo); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }
  // 화살표 (파동활동 플럭스)
  if (opt.arrows) {
    const { fx, fy } = opt.arrows; const mags = [];
    for (let i = 0; i < fx.a.length; i++) if (Number.isFinite(fx.a[i]) && Number.isFinite(fy.a[i])) mags.push(Math.hypot(fx.a[i], fy.a[i]));
    mags.sort((a, b) => a - b);
    const ref = mags[Math.floor(mags.length * 0.97)] || 1, thr = mags[Math.floor(mags.length * 0.55)] || 0;
    ctx.strokeStyle = ctx.fillStyle = V.isDark() ? "#f0f0f0" : "#191919"; ctx.lineWidth = dpr * 1.1;
    for (let i = 0; i < fx.nlat; i++) for (let j = 0; j < fx.nlon; j++) {
      const k = i * fx.nlon + j, u = fx.a[k], v = fy.a[k];
      const lat = fx.lat0 + i * fx.dlat, lon = fx.lon0 + j * fx.dlon;
      if (!Number.isFinite(u) || !Number.isFinite(v) || lat < 20 || Math.hypot(u, v) < thr) continue;
      const [x0, y0] = P(lat, lon);
      // 국지 동쪽·북쪽 방향 단위벡터를 투영에서 구한다
      const [xe, ye] = P(lat, lon + 1), [xn, yn] = P(lat + 1, lon);
      let ex = xe - x0, ey = ye - y0, nx = xn - x0, ny = yn - y0;
      const le = Math.hypot(ex, ey) || 1, ln = Math.hypot(nx, ny) || 1; ex /= le; ey /= le; nx /= ln; ny /= ln;
      const L = Math.min(Math.hypot(u, v) / ref, 1.4) * 16 * dpr, m = Math.hypot(u, v);
      const dx = (u * ex + v * nx) / m * L, dy = (u * ey + v * ny) / m * L;
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + dx, y0 + dy); ctx.stroke();
      const a = Math.atan2(dy, dx), h = 4 * dpr;
      ctx.beginPath(); ctx.moveTo(x0 + dx, y0 + dy);
      ctx.lineTo(x0 + dx - h * Math.cos(a - 0.45), y0 + dy - h * Math.sin(a - 0.45));
      ctx.lineTo(x0 + dx - h * Math.cos(a + 0.45), y0 + dy - h * Math.sin(a + 0.45)); ctx.fill();
    }
  }
  if (opt.marker) {
    const [x, y] = P(opt.marker[0], opt.marker[1]);
    ctx.fillStyle = V.isDark() ? "#ffffff" : "#191919"; ctx.strokeStyle = V.isDark() ? "#191919" : "#ffffff"; ctx.lineWidth = 1.5 * dpr;
    ctx.beginPath(); ctx.arc(x, y, 3.5 * dpr, 0, 7); ctx.fill(); ctx.stroke();
  }
  canvas._inv = (cx, cy) => {
    const x = cx * dpr, y = cy * dpr;
    return opt.proj.circle ? opt.proj.inv(x, y, W) : opt.proj.inv(x, y, W, H);
  };
};

// 지도 위 마우스 값 표시
V.hover = (canvas, tip, getter) => {
  const move = (ev) => {
    const r = canvas.getBoundingClientRect();
    const ll = canvas._inv && canvas._inv(ev.clientX - r.left, ev.clientY - r.top);
    if (!ll) { tip.style.display = "none"; return; }
    const txt = getter(ll[0], ll[1]);
    if (!txt) { tip.style.display = "none"; return; }
    tip.innerHTML = txt; tip.style.display = "block";
    const x = ev.clientX - r.left + 12, y = ev.clientY - r.top + 12;
    tip.style.left = Math.min(x, r.width - tip.offsetWidth - 4) + "px"; tip.style.top = y + "px";
  };
  canvas.onpointermove = move; canvas.onpointerleave = () => (tip.style.display = "none");
};
V.llText = (lat, lon) => `${lat.toFixed(1)}°N, ${(lon > 180 ? 360 - lon : lon).toFixed(1)}°${lon > 180 ? "W" : "E"}`;

// ---------------------------------------------------------------- SVG
const NS = "http://www.w3.org/2000/svg";
V.el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};
V.ticks = (lo, hi, n = 4) => {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const s = [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= raw) || raw;
  const out = []; for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(10));
  return out;
};

// 눈금 간격에 맞춘 소수 자리 (20, 0.5, 0.25 → 0, 1, 2자리)
V.tickFmt = (ticks) => { const st = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1; const nd = st >= 1 ? 0 : st >= 0.1 ? 1 : 2;
  return (t) => (t === 0 ? "0" : (t < 0 ? "−" : "") + Math.abs(t).toFixed(nd)); };

// 시계열: 실제 화면 폭(px)으로 그려 글자가 줄어들지 않게 한다. 다시 그리려면 같은 상자로 다시 부른다(창 크기가 바뀔 때).
// o = {title, unit, dates(ISO 문자열 또는 눈금 문자열), series: [{name, values, color, dash, width}],
//      area: {lo, hi, name}(범위 띠), bands: [{start, end, kind}], marks: [{date, label}], nd, zero, height, xticks, group}
// 같은 group의 그림은 마우스를 올린 날짜의 십자선·점·범례 값을 함께 보인다.
V._groups = {};
V.lineChart = (box, o) => {
  box.innerHTML = ""; box.classList.add("lc");
  const head = document.createElement("div"); head.className = "lc-head";
  const tr = document.createElement("div"); tr.className = "lc-tr"; head.appendChild(tr);
  const ttl = document.createElement("h3"); ttl.className = "lc-title"; ttl.textContent = o.title; tr.appendChild(ttl);
  const lg = document.createElement("div"); lg.className = "lc-legend"; head.appendChild(lg);
  const plot = document.createElement("div"); plot.className = "lc-plot";
  box.append(head, plot);
  const W = Math.max(260, Math.round(plot.clientWidth || 600)), H = o.height || 196, m = { l: 42, r: 10, t: 18, b: 24 };
  const svg = V.el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.title }); plot.appendChild(svg);
  const n = o.dates.length, named = o.series.filter((x) => x.name);
  let lo = Infinity, hi = -Infinity;
  const scan = (arr) => { for (const v of arr || []) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
  for (const x of o.series) scan(x.values);
  if (o.area) { scan(o.area.lo); scan(o.area.hi); }
  if (o.zero !== false) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (!Number.isFinite(lo)) { lo = -1; hi = 1; }
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  const X = (i) => m.l + (i / Math.max(n - 1, 1)) * (W - m.l - m.r), Y = (v) => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);
  const di = (d) => o.dates.indexOf(d), y0 = m.t, y1 = H - m.b;
  // 사건·선택 기간 띠 (이름은 띠 아래쪽 안에)
  const BAND_TXT = { sel: "선택 기간", block: "블로킹" };
  for (const b of o.bands || []) {
    let a = di(b.start), e = di(b.end); if (a < 0 && b.start < o.dates[0]) a = 0; if (e < 0 && b.end > o.dates[n - 1]) e = n - 1;
    if (a < 0 || e < 0) continue;
    const bx = X(a) - 1.5, bw = Math.max(X(e) - X(a) + 3, 3);
    V.el("rect", { x: bx, y: y0, width: bw, height: y1 - y0, fill: `var(--band-${b.kind})` }, svg);
    // 이름은 그림 위 여백에 (선과 겹치지 않게). 띠가 좁으면 생략하고 절 설명문에 맡긴다
    if (BAND_TXT[b.kind] && bw > 24) V.el("text", { x: bx + 2, y: y0 - 4, class: "lc-band" }, svg).textContent = BAND_TXT[b.kind];
  }
  // 가로 눈금
  const yt = V.ticks(lo, hi, 4), yf = V.tickFmt(yt);
  for (const t of yt) {
    V.el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "lc-zero" : "lc-grid" }, svg);
    V.el("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end", class: "lc-tick" }, svg).textContent = yf(t);
  }
  // 세로 눈금: 달 첫날(또는 지정 눈금)
  if (o.xticks) for (const d of o.xticks) { const i = di(d); if (i < 0) continue;
    V.el("line", { x1: X(i), x2: X(i), y1: y0, y2: y1, class: "lc-grid" }, svg);
    V.el("text", { x: X(i), y: H - 6, "text-anchor": "middle", class: "lc-tick" }, svg).textContent = d; }
  else for (let i = 0; i < n; i++) { const d = o.dates[i]; if (!d.endsWith("-01")) continue;
    V.el("line", { x1: X(i), x2: X(i), y1: y0, y2: y1, class: "lc-grid" }, svg);
    V.el("text", { x: X(i) + 3, y: H - 6, class: "lc-tick" }, svg).textContent = `${+d.slice(5, 7)}월`; }
  // 범위 띠 (예: 과거 사례 5~95%)
  if (o.area) {
    let d = "", up = [], dn = [];
    for (let i = 0; i < n; i++) if (Number.isFinite(o.area.lo[i]) && Number.isFinite(o.area.hi[i])) { up.push([X(i), Y(o.area.hi[i])]); dn.push([X(i), Y(o.area.lo[i])]); }
    if (up.length) { d = "M" + up.map((p) => p.join(" ")).join("L") + "L" + dn.reverse().map((p) => p.join(" ")).join("L") + "Z";
      V.el("path", { d, class: "lc-area" }, svg); }
  }
  for (const mk of o.marks || []) {
    const i = di(mk.date); if (i < 0) continue;
    V.el("line", { x1: X(i), x2: X(i), y1: y0, y2: y1, class: "lc-mark" }, svg);
    V.el("text", { x: X(i) + 4, y: y0 + 10, class: "lc-marktxt" }, svg).textContent = mk.label;
  }
  for (const x of o.series) {
    let d = "", pen = false;
    x.values.forEach((v, i) => { if (Number.isFinite(v)) { d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; } else pen = false; });
    V.el("path", { d, fill: "none", stroke: x.color, "stroke-width": x.width || 1.8, "stroke-dasharray": x.dash || "", "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  }
  // 범례: 선 모양 + 이름 + 그날 값 (기본은 마지막 값). 색만으로 계열을 가리지 않게 값을 글자로 둔다
  const fmt = (v) => (Number.isFinite(v) ? V.sgn(v, o.nd ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2)) : "–");
  const keys = named.map((x) => {
    const k = document.createElement("span"); k.className = "lc-key";
    k.innerHTML = `<svg width="18" height="10" aria-hidden="true"><line x1="1" x2="17" y1="5" y2="5" stroke="${x.color}" stroke-width="${x.width ? Math.max(2, x.width) : 2.4}" stroke-dasharray="${x.dash || ""}" stroke-linecap="round"/></svg>${x.name} <b></b>`;
    lg.appendChild(k); return k.querySelector("b");
  });
  if (o.area && o.area.name) { const k = document.createElement("span"); k.className = "lc-key"; k.innerHTML = `<i class="lc-areakey"></i>${o.area.name}`; lg.appendChild(k); }
  const dateEl = document.createElement("span"); dateEl.className = "lc-date"; tr.appendChild(dateEl);
  // 기본으로 보이는 날: 모든 계열에 값이 있는 마지막 날(없으면 어느 하나라도 있는 마지막 날)
  const lastBy = (f) => { for (let i = n - 1; i >= 0; i--) if (f(i)) return i; return -1; };
  let lastIdx = lastBy((i) => named.every((x) => Number.isFinite(x.values[i])));
  if (lastIdx < 0) lastIdx = Math.max(0, lastBy((i) => named.some((x) => Number.isFinite(x.values[i]))));
  const setKeys = (i) => { named.forEach((x, k) => (keys[k].textContent = fmt(x.values[i]) + (o.unit && Number.isFinite(x.values[i]) ? " " + o.unit : "")));
    dateEl.textContent = o.xticks ? `${o.dates[i]}일` : o.dates[i]; };
  setKeys(lastIdx);
  // 십자선, 점, 풍선 도움말
  const cross = V.el("line", { y1: y0, y2: y1, class: "lc-cross", visibility: "hidden" }, svg);
  const dots = named.map((x) => V.el("circle", { r: 3.5, fill: x.color, class: "lc-dot", visibility: "hidden" }, svg));
  const tip = document.createElement("div"); tip.className = "tip"; plot.appendChild(tip);
  const show = (d, withTip) => {
    const i = di(d);
    if (i < 0) { hide(); return; }
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
    named.forEach((x, k) => { const v = x.values[i]; if (Number.isFinite(v)) { dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(v)); dots[k].setAttribute("visibility", "visible"); } else dots[k].setAttribute("visibility", "hidden"); });
    setKeys(i);
    if (withTip) {
      tip.innerHTML = `<b>${o.xticks ? "발생 후 " + o.dates[i] + "일" : o.dates[i]}</b><br>` + named.map((x) => `<span class="sw" style="background:${x.color}"></span>${x.name} ${fmt(x.values[i])}${o.unit ? " " + o.unit : ""}`).join("<br>");
      tip.style.display = "block";
      const left = X(i) + 12 + tip.offsetWidth > W ? X(i) - 12 - tip.offsetWidth : X(i) + 12;
      tip.style.left = Math.max(0, left) + "px"; tip.style.top = "6px";
    } else tip.style.display = "none";
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); dots.forEach((c) => c.setAttribute("visibility", "hidden")); tip.style.display = "none"; setKeys(lastIdx); };
  box._lc = { show, hide };
  const peers = () => { const g = o.group ? (V._groups[o.group] = (V._groups[o.group] || []).filter((b) => b.isConnected)) : [box]; return g; };
  if (o.group) { V._groups[o.group] = (V._groups[o.group] || []).filter((b) => b.isConnected && b !== box); V._groups[o.group].push(box); }
  const hit = V.el("rect", { x: m.l, y: y0, width: W - m.l - m.r, height: y1 - y0, fill: "transparent", class: "lc-hit" }, svg);
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - r.left - m.l) / (W - m.l - m.r) * (n - 1))));
    for (const b of peers()) b._lc && b._lc.show(o.dates[i], b === box);
  });
  hit.addEventListener("pointerleave", () => { for (const b of peers()) b._lc && b._lc.hide(); });
};

// 가로 막대 (기여도·상관): rows = [{label, value, lo, hi, kind, faded, note}]. 실제 화면 폭(px)으로 그린다.
// 좁은 화면(480 px 미만)에서는 이름을 막대 위 줄에 둔다.
V.barChart = (box, rows, o) => {
  box.innerHTML = ""; box.classList.add("lc");
  const ttl = document.createElement("h3"); ttl.className = "lc-title"; ttl.textContent = o.title;
  const plot = document.createElement("div"); plot.className = "lc-plot"; box.append(ttl, plot);
  const W = Math.max(260, Math.round(plot.clientWidth || 600)), narrow = W < 480;
  const rowH = narrow ? 42 : 28, m = { l: narrow ? 6 : Math.min(o.ml || 150, W * 0.4), r: 52, t: 6, b: 22 }, H = m.t + m.b + rows.length * rowH;
  const svg = V.el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.title }); plot.appendChild(svg);
  let lo = 0, hi = 0;
  for (const r of rows) for (const v of [r.value, r.lo, r.hi]) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const pad = (hi - lo) * 0.06 || 0.1; lo -= pad; hi += pad;
  const X = (v) => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
  const xt = V.ticks(lo, hi, narrow ? 4 : 5), xf = V.tickFmt(xt);
  for (const t of xt) {
    V.el("line", { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: t === 0 ? "lc-zero" : "lc-grid" }, svg);
    V.el("text", { x: X(t), y: H - 6, "text-anchor": "middle", class: "lc-tick" }, svg).textContent = xf(t);
  }
  const tip = document.createElement("div"); tip.className = "tip"; plot.appendChild(tip);
  rows.forEach((r, i) => {
    const top = m.t + i * rowH, h = 14, y = narrow ? top + 22 : top + (rowH - h) / 2;
    if (narrow) V.el("text", { x: m.l, y: top + 14, class: "lc-lab" }, svg).textContent = r.label;
    else V.el("text", { x: m.l - 8, y: y + h - 2, "text-anchor": "end", class: "lc-lab" }, svg).textContent = r.label;
    const col = r.kind === "resid" ? "var(--ink-3)" : r.kind === "obs" ? "var(--ink)" : r.value >= 0 ? "var(--warm)" : "var(--cool)";
    const x0 = X(Math.min(0, r.value)), w = Math.max(Math.abs(X(r.value) - X(0)), 1.5);
    const bar = V.el("rect", { x: x0, y, width: w, height: h, rx: 3, fill: col, opacity: r.faded ? 0.4 : 1 }, svg);
    if (Number.isFinite(r.lo)) {
      V.el("line", { x1: X(r.lo), x2: X(r.hi), y1: y + h / 2, y2: y + h / 2, class: "lc-ci" }, svg);
      for (const v of [r.lo, r.hi]) V.el("line", { x1: X(v), x2: X(v), y1: y + 2, y2: y + h - 2, class: "lc-ci" }, svg);
    }
    V.el("text", { x: Math.max(X(r.value), X(0), Number.isFinite(r.hi) ? X(r.hi) : 0) + 6, y: y + h - 2, class: "lc-val" }, svg).textContent = V.sgn(r.value, 2);
    const hitR = V.el("rect", { x: 0, y: top, width: W, height: rowH, fill: "transparent" }, svg);
    const showTip = () => {
      tip.innerHTML = `<b>${r.label}</b><br>${V.sgn(r.value, 2)} ${o.unit}` + (Number.isFinite(r.lo) ? `<br>구간 ${V.sgn(r.lo, 2)} ~ ${V.sgn(r.hi, 2)}` : "") + (r.note ? `<br>${r.note}` : "");
      tip.style.display = "block"; tip.style.left = Math.max(0, Math.min(X(Math.max(0, r.value)) + 10, W - tip.offsetWidth - 2)) + "px";
      tip.style.top = Math.max(0, top + rowH) + "px"; bar.setAttribute("stroke", "var(--ink)");
    };
    hitR.addEventListener("pointerenter", showTip); hitR.addEventListener("pointermove", showTip);
    hitR.addEventListener("pointerleave", () => { tip.style.display = "none"; bar.removeAttribute("stroke"); });
  });
};

// 연직-시간 단면 (극관 고도): v[level][day]
V.heat = (canvas, o) => {
  const dpr = Math.min(window.devicePixelRatio || 1, 2), cssW = canvas.clientWidth || 600, cssH = o.height || 180;
  canvas.width = cssW * dpr; canvas.height = cssH * dpr; canvas.style.height = cssH + "px";
  const ctx = canvas.getContext("2d"), ml = 40 * dpr, mb = 18 * dpr, W = canvas.width - ml, H = canvas.height - mb;
  const nl = o.levels.length, nd = o.v[0].length;
  const ly = (p) => (Math.log(p) - Math.log(o.levels[0])) / (Math.log(o.levels[nl - 1]) - Math.log(o.levels[0])) * H;
  for (let l = 0; l < nl; l++) {
    const y0 = l === 0 ? 0 : (ly(o.levels[l - 1]) + ly(o.levels[l])) / 2, y1 = l === nl - 1 ? H : (ly(o.levels[l]) + ly(o.levels[l + 1])) / 2;
    for (let d = 0; d < nd; d++) {
      const v = o.v[l][d]; const [r, g, b] = Number.isFinite(v) ? V.divColor(Math.round(v / o.vmax * 6) / 6) : [128, 128, 128];
      ctx.fillStyle = `rgb(${r},${g},${b})`; ctx.fillRect(ml + d / nd * W, y0, W / nd + 1, y1 - y0 + 1);
    }
  }
  ctx.fillStyle = V.css("--ink-2"); ctx.font = `${11 * dpr}px sans-serif`; ctx.textAlign = "right";
  for (const p of [10, 30, 100, 300, 1000]) ctx.fillText(String(p), ml - 4 * dpr, ly(p) + 4 * dpr);
  ctx.textAlign = "center";
  o.dates.forEach((d, i) => { if (d.endsWith("-01")) ctx.fillText(`${+d.slice(5, 7)}월`, ml + (i + 0.5) / nd * W, H + 14 * dpr); });
  for (const mk of o.marks || []) {
    const i = o.dates.indexOf(mk); if (i < 0) continue;
    ctx.strokeStyle = V.css("--ink"); ctx.setLineDash([4 * dpr, 3 * dpr]); ctx.beginPath();
    ctx.moveTo(ml + (i + 0.5) / nd * W, 0); ctx.lineTo(ml + (i + 0.5) / nd * W, H); ctx.stroke(); ctx.setLineDash([]);
  }
  canvas._pick = (cx, cy) => {
    const x = cx * dpr - ml, y = cy * dpr; if (x < 0 || y > H) return null;
    const d = Math.floor(x / W * nd); let l = 0; for (let k = 0; k < nl; k++) if (Math.abs(ly(o.levels[k]) - y) < Math.abs(ly(o.levels[l]) - y)) l = k;
    return { date: o.dates[d], level: o.levels[l], v: o.v[l][d] };
  };
};
window.V = V;
