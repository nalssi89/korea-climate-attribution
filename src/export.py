"""6·7단계: 정적 대시보드(site/)와 three.js 모식도(site/schematic/)가 읽는 축약 JSON을 내보낸다.

- 격자는 정수로 양자화해 {"lat0","dlat","nlat","lon0","dlon","nlon","scale","offset","v"} 꼴로 담는다
  (실제 값 = v * scale + offset, 결측은 null).
- KMA 관측은 원자료를 넣지 않고 전국 평균 편차 같은 집계값만 넣는다 (공개 저장소).
- 사이트의 모든 경로는 상대 경로라 /korea-climate-attribution/ 아래에서도 열린다.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil

import numpy as np
import pandas as pd
import xarray as xr

from . import config as C
from .common import anomaly, field_clim, get_logger, open_field, series_clim, skt_clim, window_anom

log = get_logger("export")
SITE = C.ROOT / "site"
DATA = SITE / "data"

# 대시보드 지도에 쓰는 장: 이름 -> (한국어 이름, 단위, 양자화 간격)
NH_FIELDS = {"z500": ("500 hPa 고도", "m", 1.0), "msl": ("해면기압", "hPa", 0.1), "t850": ("850 hPa 기온", "°C", 0.1),
             "u250": ("250 hPa 동서풍", "m/s", 0.1), "z10": ("10 hPa 고도", "m", 1.0), "t10": ("10 hPa 기온", "°C", 0.1)}
DAILY_KEYS = ["u1060", "pv", "t10_cap_anom", "vt100_anom", "wave1", "wave2", "vortex_lat", "vortex_lon", "vortex_pieces",
              "pch10", "pch100", "pch500", "ural", "blocked", "aleutian", "nino34", "ao", "nao", "pna", "wp", "eu", "scand",
              "siberian_high", "ea_jet", "eawm", "phil_sea", "bk_ice", "korea_t", "korea_p", "ea_t", "ea_p", "nchina_t",
              "schina_t", "japan_t", "mongolia_t", "asos_t", "asos_p"]


def _q(a: np.ndarray, scale: float, offset: float = 0.0) -> list:
    v = np.round((np.asarray(a, dtype="float64") - offset) / scale)
    return [None if not np.isfinite(x) else int(x) for x in v.ravel()]


def _pack(a: np.ndarray, scale: float, offset: float, int8: bool = False) -> dict:
    """양자화한 정수를 int8(범위가 되면) 또는 int16 리틀엔디언으로 묶어 base64로 싣는다. 결측은 가장 작은 정수.

    JSON의 정수 목록보다 4~6배 작다 (모식도 자료를 5 MB 안쪽으로 유지하려고 쓴다). 해독은 site/assets/viz.js의 V.decode.
    """
    import base64
    v = np.round((np.asarray(a, dtype="float64") - offset) / scale)
    ok = np.isfinite(v)
    if int8:            # 1바이트로 강제: 범위 밖 값은 끝값으로 자른다 (양자화 간격을 그만큼 넉넉히 고른 장에만 쓴다)
        v = np.where(ok, np.clip(v, -127, 127), v)
    lo, hi = (v[ok].min(), v[ok].max()) if ok.any() else (0, 0)
    dt_, fill = ("<i1", -128) if lo > -128 and hi <= 127 else ("<i2", -32768)
    assert lo > -32768 and hi <= 32767, "int16 범위를 넘는다: 양자화 간격을 키워야 한다"
    q = np.where(ok, v, fill).astype(dt_)
    return dict(b64=base64.b64encode(q.tobytes()).decode(), dtype="i1" if dt_ == "<i1" else "i2")


def grid(da, lat, lon, scale: float, offset: float = 0.0, pack: bool = False, int8: bool = False) -> dict:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    out = dict(lat0=round(float(lat[0]), 3), dlat=round(float(lat[1] - lat[0]), 3), nlat=int(lat.size),
               lon0=round(float(lon[0]), 3), dlon=round(float(lon[1] - lon[0]), 3), nlon=int(lon.size),
               scale=scale, offset=offset)
    if pack:
        out.update(_pack(np.asarray(da), scale, offset, int8))
    else:
        out["v"] = _q(np.asarray(da), scale, offset)
    return out


def _r(x, nd=3):
    """JSON에 넣을 숫자를 줄인다 (중첩 구조 전체)."""
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), nd)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _dump(obj, path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = json.dumps(_r(obj), ensure_ascii=False, separators=(",", ":"))
    path.write_text(s)
    return len(s)


# ------------------------------------------------------------------ 기간별 파일
def period_file(res: dict) -> dict:
    p = res["period"]
    start, end = p["start"], p["eff_end"]
    nh = {}
    for name, (label, unit, sc) in NH_FIELDS.items():
        da = window_anom(name, start, end).isel(lat=slice(None, None, 2), lon=slice(None, None, 2))
        nh[name] = dict(label=label, unit=unit, **grid(da.values, da.lat, da.lon, sc))
    from .diagnose import dynamics
    w = dynamics.tn_flux(start, end)
    ws = w.isel(lat=slice(None, None, 4), lon=slice(None, None, 4))
    waf = dict(fx=grid(ws.fx.values, ws.lat, ws.lon, 0.1), fy=grid(ws.fy.values, ws.lat, ws.lon, 0.1))
    za = w.za.isel(lat=slice(None, None, 2), lon=slice(None, None, 2))
    nh["waf"] = dict(label="250 hPa 파동활동 플럭스와 고도 편차", unit="m", **grid(za.values, za.lat, za.lon, 1.0), arrows=waf)
    ea = {}
    for name, m in res["attribution"]["maps"].items():
        sc = 0.05
        ea[name] = dict(obs=grid(m["obs"], m["lat"], m["lon"], sc), resid=grid(m["resid"], m["lat"], m["lon"], sc),
                        r2cv=grid(m["r2cv"], m["lat"], m["lon"], 0.01),
                        contrib={f: grid(v, m["lat"], m["lon"], 0.01) for f, v in m["contrib"].items()})
    att = {k: v for k, v in res["attribution"].items() if k != "maps"}
    return dict(period=p, indices=res["indices"], regions=res["regions"], attribution=att,
                sentences=res["sentences"], blocked_days=res["blocked_days"], nh=nh, ea=ea)


# ------------------------------------------------------------------ 일별 지수, 사건
def indices_file(df: pd.DataFrame, end: pd.Timestamp, back: int = 150) -> dict:
    t0 = end - pd.Timedelta(days=back - 1)
    d = df[t0:end]
    ser = {k: d[k].tolist() for k in DAILY_KEYS if k in d}
    ser["u1060_clim"] = series_clim(df["u1060"])[t0:end].tolist()
    ub = pd.read_csv(C.OUT / "events_ural_blocking.csv")
    ub = ub[pd.to_datetime(ub.end) >= t0]
    try:
        ssw = pd.read_csv(C.OUT / "events_ssw.csv")
    except pd.errors.EmptyDataError:
        ssw = pd.DataFrame(columns=["date"])
    oni = pd.read_csv(C.OUT / "oni_monthly.csv", index_col=0, parse_dates=True)["oni"].dropna()
    enso = [dict(month=f"{t:%Y-%m}", oni=float(v), phase="엘니뇨" if v >= C.ONI_THRESHOLD else
                 ("라니냐" if v <= -C.ONI_THRESHOLD else "중립")) for t, v in oni[-6:].items()]
    return dict(start=str(t0.date()), end=str(end.date()), series=ser,
                events=dict(ural_blocking=json.loads(ub.to_json(orient="records", force_ascii=False)),
                            ssw=json.loads(ssw.to_json(orient="records", force_ascii=False, date_format="iso"))),
                enso=enso)


def ssw_file(case: dict, end: pd.Timestamp, back: int = 120) -> dict:
    pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc")
    t0 = end - pd.Timedelta(days=back - 1)
    p = pch.sel(time=slice(t0, end))
    return dict(case=case, pch=dict(start=str(t0.date()), levels=[int(l) for l in p.level.values],
                                    v=_q(p.values.T, 0.01)))


# ------------------------------------------------------------------ 모식도용 일별 축약 자료
def schematic_file(df: pd.DataFrame, end: pd.Timestamp, case: dict, days: int = 90) -> dict:
    from .diagnose import dynamics
    t0 = end - pd.Timedelta(days=days - 1)
    times = pd.date_range(t0, end)
    sl = dict(lat=slice(18, 90))
    s3 = dict(lat=slice(None, None, 2), lon=slice(None, None, 2))    # 1.5° → 3°
    s45 = dict(lat=slice(None, None, 3), lon=slice(None, None, 3))   # 1.5° → 4.5°
    out = dict(start=str(t0.date()), end=str(end.date()), n=len(times), fields={})
    # 모든 장은 북반구(또는 전지구) 격자 그대로 싣는다. 동아시아만 따로 자르지 않는다.
    # 화면에서 3차 보간으로 1.5° 간격까지 부드럽게 다시 그린다.

    def daily(name, anom=True):
        da = open_field(name).sel(time=slice(t0, end)).load()
        if anom:
            da = anomaly(da, field_clim(name))
        return da

    def put(key, da, unit, sc, offset=0.0, int8=False):
        out["fields"][key] = dict(unit=unit, **grid(da.values, da.lat, da.lon, sc, offset, pack=True, int8=int8))

    # 10 hPa: 고도(극소용돌이 모양)와 기온 편차(승온)
    put("z10", daily("z10", anom=False).sel(**sl).isel(**s45), "m", 10.0, 30000.0)
    # 극소용돌이 가장자리: 그날의 평년 60°N 동서평균 10 hPa 고도 (indices.strat.vortex_geometry와 같은 정의)
    edge = series_clim(open_field("z10").sel(lat=60.0).mean("lon").to_series())[t0:end]
    out["z10_edge"] = edge.round(0).tolist()
    put("t10_anom", daily("t10").sel(**sl).isel(**s45), "K", 0.2)
    # 250 hPa 바람(풍속 등치선용), 500 hPa 고도 편차: 3°
    # 용량(5 MB 안쪽)을 위해 1바이트로 싣는다: 바람 1 m/s(±127), 고도 편차 4 m(±508 m) 간격. 화면 등치선 간격(10 m/s, 60 m)보다 충분히 잘다
    put("u250", daily("u250", anom=False).sel(**sl).isel(**s3), "m/s", 1.0, int8=True)
    put("v250", daily("v250", anom=False).sel(**sl).isel(**s3), "m/s", 1.0, int8=True)
    put("z500_anom", daily("z500").sel(**sl).isel(**s3), "m", 4.0, int8=True)
    # 지상: 해면기압 편차, 해수면온도 편차, 해빙, 육지 2 m 기온 편차
    put("msl_anom", daily("msl").sel(lat=slice(0, 90)).isel(**s45), "hPa", 0.4, int8=True)      # ±50 hPa
    sst = daily("sst")
    put("sst_anom", sst.sel(lat=slice(-30, 90)).isel(**s45), "°C", 0.1, int8=True)            # ±12.7 °C
    ci = daily("ci", anom=False)
    ci_clim = ci - daily("ci")
    put("ci", ci.sel(lat=slice(39, 90)).isel(**s3), "비율", 0.01)
    put("ci_clim", ci_clim.sel(lat=slice(39, 90)).isel(**s3), "비율", 0.01)
    t2 = daily("t2m")
    if float(t2.lat.min()) < 10:       # 북반구 전체로 받은 경우: 바다(해빙 없는 곳)는 해수면온도로 보이므로 육지만 싣는다
        sea = sst.notnull().reindex(lat=t2.lat, lon=t2.lon, method="nearest") & \
            (ci.reindex(lat=t2.lat, lon=t2.lon, method="nearest").fillna(0) < 0.15)
        t2 = t2.where(~sea)
    else:
        log.warning("t2m이 동아시아 영역만 있어 모식도 지상 기온도 그 영역만 그린다 (fetch에서 북반구로 받아야 함)")
    put("t2m_anom", t2.sel(lat=slice(0, 90)).isel(**s3), "°C", 0.2)
    # 눈덮임 비율(눈 깊이에서 만든 0~1, forcing.ensure_snowc): 모식도가 50% 경계선을 그린다. 눈이 있을 수 있는 위도만 싣는다
    if (C.DATA / "merged" / "snowc.nc").exists():
        sc = daily("snowc", anom=False)
        sc_clim = sc - daily("snowc")
        lf = xr.open_dataarray(C.DATA / "static" / "landfrac_nh.nc").reindex(lat=sc.lat, lon=sc.lon, method="nearest")
        land = lf >= C.LAND_MIN
        put("snowc", sc.where(land).sel(lat=slice(21, 84)).isel(**s3), "비율", 0.01)
        put("snowc_clim", sc_clim.where(land).sel(lat=slice(21, 84)).isel(**s3), "비율", 0.01)
    # 지상 면 변수 선택용 (일별 장이 있을 때만): 표층 토양수분, 지표기온(skin temperature)
    for key, name, unit, scale in (("swvl1_anom", "swvl1", "m³/m³", 0.002), ("skt_anom", "skt", "°C", 0.2)):
        if (C.DATA / "merged" / f"{name}.nc").exists():
            if name == "skt":        # 일별 평년(field_clim)이 없다: CDS 월평균 평년(1991~2020)을 날짜별로 보간해 뺀다
                da = daily(name, anom=False)
                cl = skt_clim(da.time.values)
                if cl is None:
                    log.warning("CDS 월평균 지표기온 파일이 없어 모식도 지표기온 편차를 내보내지 않는다")
                    continue
                cl = cl.reindex(lat=da.lat, lon=da.lon, method="nearest", tolerance=0.01)
                da = da - cl.values
            else:
                da = daily(name)
            if name == "swvl1":      # 토양수분은 육지에서만 뜻이 있다
                lf = xr.open_dataarray(C.DATA / "static" / "landfrac_nh.nc").reindex(lat=da.lat, lon=da.lon, method="nearest")
                da = da.where(lf >= C.LAND_MIN)
            put(key, da.sel(lat=slice(21, 84) if name == "swvl1" else slice(0, 90)).isel(**s3), unit, scale)
            if name == "skt":
                out["fields"][key]["clim"] = "CDS 월평균 1991~2020을 달 가운데 날 기준으로 선형 순환 보간"
    # 파동활동 플럭스: 날마다 앞뒤 3일(7일) 평균 편차로 계산, 6° 간격
    fx, fy = [], []
    for t in times:
        a, b = t - pd.Timedelta(days=3), min(t + pd.Timedelta(days=3), end)
        w = dynamics.tn_flux(a.date(), b.date()).sel(lat=slice(24, 84)).isel(lat=slice(None, None, 4), lon=slice(None, None, 4))
        fx.append(w.fx.values)
        fy.append(w.fy.values)
    out["fields"]["waf_fx"] = dict(unit="m²/s²", **grid(np.stack(fx), w.lat, w.lon, 0.5, pack=True))
    out["fields"]["waf_fy"] = dict(unit="m²/s²", **grid(np.stack(fy), w.lat, w.lon, 0.5, pack=True))
    pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc").sel(time=slice(t0, end))
    out["pch"] = dict(levels=[int(l) for l in pch.level.values], v=_q(pch.values, 0.1))
    d = df.reindex(times)
    out["series"] = {k: d[k].tolist() for k in ("u1060", "ural", "blocked", "ao", "nino34", "t10_cap_anom", "korea_t",
                                                "ea_t", "vortex_lat", "vortex_lon", "vortex_pieces", "siberian_high",
                                                "aleutian", "vt100_anom") if k in d}
    ub = pd.read_csv(C.OUT / "events_ural_blocking.csv")
    ub = ub[(pd.to_datetime(ub.end) >= t0)]
    marks = [dict(date=str(r.onset), kind="ural", label=f"우랄블로킹 시작 ({r.duration}일)") for r in ub.itertuples()
             if pd.Timestamp(r.onset) >= t0]
    if case.get("onset"):
        marks.append(dict(date=case["onset"], kind="ssw",
                          label="SSW 발생(주 승온)" if case["kind"] == "major" else "성층권 승온(부 승온)"))
    out["marks"] = sorted(marks, key=lambda m: m["date"])
    return out


# ------------------------------------------------------------------ 강제인자 영역
def forcing_file() -> dict:
    """대시보드 '강제인자' 영역: 현재 편차 표, 시차 상관, 회귀 비교, 최근 30일 편차 지도(3°, 15°N 이북)."""
    S = json.loads((C.OUT / "forcing_summary.json").read_text())
    maps = {}
    units = {"sst": ("해수면온도", "°C", 0.05), "ci": ("해빙 농도", "%p", 0.5), "snowc": ("눈덮임 비율", "%p", 0.5),
             "swvl1": ("토양수분(0~7 cm)", "%p", 0.05), "t2m": ("육지 2 m 기온", "°C", 0.05)}
    p = C.DATA / "derived" / "forcing_maps.nc"
    if p.exists():
        ds = xr.open_dataset(p)
        for k, (label, unit, sc) in units.items():
            da = ds[k].sel(lat=slice(15, 90)).isel(lat=slice(None, None, 2), lon=slice(None, None, 2))
            maps[k] = dict(label=label, unit=unit, period="최근 30일", **grid(da.values, da.lat, da.lon, sc))
    p = C.DATA / "derived" / "skt_latest.nc"
    if p.exists():
        da = xr.open_dataset(p)["skt"]
        lf = xr.open_dataarray(C.DATA / "static" / "landfrac_nh.nc").reindex(lat=da.lat, lon=da.lon, method="nearest")
        da = da.where(lf >= C.LAND_MIN).sel(lat=slice(15, 90)).isel(lat=slice(None, None, 2), lon=slice(None, None, 2))
        maps["skt"] = dict(label="지면온도(월평균)", unit="°C", period=str(da.time.values)[:7], **grid(da.values, da.lat, da.lon, 0.05))
    lc = [{k: r[k] for k in ("season", "forcing", "target", "lag", "r", "lo", "hi", "p", "q", "n", "verdict", "fdr")} for r in S["lagcorr"]]
    return dict(end=S["end"], target_month=S["target_month"], last_year=S["last_year"], lags=S["lags"],
                season_months=S["season_months"], forcings=S["forcings"], targets=S["targets"], current=S["current"],
                lagcorr=lc, regression=S["regression"], substitute=S["substitute"], skt_last=S["skt_last"],
                snow_definition=S["snow_definition"], sentences=S["sentences"], counts=S["counts"], maps=maps)


def coastlines() -> dict:
    """Natural Earth 해안선(공개 자료). 지구본·북반구 지도는 110m, 동아시아 확대 지도는 50m."""
    import cartopy.io.shapereader as shp
    out = {}
    for res, box in (("110m", (-35, 90, -180, 180)), ("50m", (10, 62, 85, 165))):
        lines = []
        for geom in shp.Reader(shp.natural_earth(resolution=res, category="physical", name="coastline")).geometries():
            parts = getattr(geom, "geoms", [geom])
            for g in parts:
                xy = np.asarray(g.coords)
                keep = (xy[:, 1] >= box[0]) & (xy[:, 1] <= box[1]) & (xy[:, 0] >= box[2]) & (xy[:, 0] <= box[3])
                if keep.sum() < 2:
                    continue
                # 영역 밖으로 나간 구간에서 선을 끊는다
                seg = []
                for (x, y), k in zip(xy, keep):
                    if k:
                        seg += [round(float(x), 2), round(float(y), 2)]
                    elif len(seg) >= 4:
                        lines.append(seg)
                        seg = []
                    else:
                        seg = []
                if len(seg) >= 4:
                    lines.append(seg)
        out[res] = lines
    return out


def run(end, periods_res: list[dict], r2_rows: list[dict], case: dict, df: pd.DataFrame) -> None:
    end = pd.Timestamp(end)
    if (DATA / "periods").exists():
        shutil.rmtree(DATA / "periods")
    sizes = {}
    plist = []
    for res in periods_res:
        pid = res["period"]["pid"]
        sizes[pid] = _dump(period_file(res), DATA / "periods" / f"{pid}.json")
        plist.append({k: res["period"][k] for k in ("pid", "kind", "kind_label", "label", "start", "end", "eff_end",
                                                   "n_days", "full_days", "complete")})
    status = json.loads((C.OUT / "fetch_status.json").read_text()) if (C.OUT / "fetch_status.json").exists() else {}
    tele = json.loads((C.OUT / "teleconnection_modes.json").read_text()) if (C.OUT / "teleconnection_modes.json").exists() else {}
    from .attribute.regression import FACTOR_LABEL
    from .diagnose import INDEX_LABEL
    meta = dict(generated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), data_end=str(end.date()),
                clim=list(C.CLIM), start_year=C.START_YEAR, periods=plist, r2_by_kind=r2_rows,
                regions=[dict(key=k, name=v[0], box=list(v[1])) for k, v in C.EA_SUBREGIONS.items()],
                factors=[dict(key=k, label=FACTOR_LABEL[k], lag=C.DRIVERS[k]) for k in C.DRIVERS],
                index_label={k: list(v) for k, v in INDEX_LABEL.items()}, tele_label=C.TELE_LABEL, tele=tele,
                fields={k: dict(label=v[0], unit=v[1]) for k, v in NH_FIELDS.items()},
                status={k: v for k, v in status.items()},
                rules=dict(sigma_strong=C.SIGMA_STRONG, sigma_weak=C.SIGMA_WEAK))
    sizes["meta"] = _dump(meta, DATA / "meta.json")
    sizes["indices"] = _dump(indices_file(df, end), DATA / "indices.json")
    sizes["ssw"] = _dump(ssw_file(case, end), DATA / "ssw.json")
    sizes["schematic"] = _dump(schematic_file(df, end, case), DATA / "schematic.json")
    if (C.OUT / "forcing_summary.json").exists():
        sizes["forcing"] = _dump(forcing_file(), DATA / "forcing.json")
    coast = DATA / "coast.json"
    if not coast.exists():
        sizes["coast"] = _dump(coastlines(), coast)
    tot = sum(sizes.values())
    log.info("site/data 갱신: %d개 파일, %.1f MB (가장 큰 것 %s)", len(sizes), tot / 1e6, max(sizes, key=sizes.get))
