"""3단계: 최근 한 달 진단 (편차장 지도, 일별 시계열, 파동활동 플럭스, 하층 이류·수증기 수송)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import xarray as xr

from .. import config as C
from ..common import (BLUE, COOL, INK2, ORANGE, WARM, diverging_cmap, get_logger, load_indices,
                      same_season_windows, savefig, series_clim, setup_plot, window_anom)

log = get_logger("diagnose")

INDEX_LABEL = {
    "korea_t": ("한반도 기온 편차", "°C"), "korea_p": ("한반도 강수 편차", "mm/일"),
    "ural": ("우랄 Z500 편차", "m"), "pv": ("10 hPa 60°N 동서풍 편차", "m/s"),
    "nino34": ("Niño3.4 편차", "°C"), "ao": ("북극진동(AO)", "σ"),
    "siberian_high": ("시베리아 고기압 편차", "hPa"), "ea_jet": ("동아시아 제트 편차", "m/s"),
    "eawm": ("겨울몬순 지수 편차", "m/s"), "phil_sea": ("필리핀해 해면기압 편차", "hPa"),
    "bk_ice": ("바렌츠-카라 해빙 편차", "비율"), "pch10": ("극관 고도 10 hPa", "σ"),
    "pch500": ("극관 고도 500 hPa", "σ"), "pch100": ("극관 고도 100 hPa", "σ"),
    "u1060": ("10 hPa 60°N 동서풍", "m/s"), "t10_cap_anom": ("극관 10 hPa 기온 편차", "K"),
    "vt100_anom": ("100 hPa 에디 열속 편차", "K·m/s"), "aleutian": ("알류샨 해면기압 편차", "hPa"),
    "blocked": ("우랄 블로킹일", "일"), "nao": ("북대서양진동(NAO)", "σ"), "pna": ("태평양-북미(PNA)", "σ"),
    "wp": ("서태평양(WP)", "σ"), "eu": ("유라시아(EU)", "σ"), "scand": ("스칸디나비아(SCAND)", "σ"),
}


def _cyclic(da: xr.DataArray) -> xr.DataArray:
    return xr.concat([da, da.isel(lon=0).assign_coords(lon=360.0)], "lon")


def _levels(da: xr.DataArray, step_candidates, n: int = 8) -> np.ndarray:
    """편차 크기에 맞춰 0을 가운데 둔 등간격 단계를 고른다."""
    vmax = float(np.nanpercentile(np.abs(da.values), 99.5))
    step = next((s for s in step_candidates if s * n >= vmax), step_candidates[-1])
    lev = np.arange(-n, n + 1) * step
    return lev[lev != 0]


def plot_maps(start, end) -> dict:
    """Z500, 해면기압, 10 hPa 고도, T850, U200, 해수면온도 편차장."""
    plt = setup_plot()
    import cartopy.crs as ccrs
    cmap = diverging_cmap()
    spec = [("z500", "500 hPa 고도 편차 (m)", "polar", (10, 20, 30, 40, 60, 80)),
            ("msl", "해면기압 편차 (hPa)", "polar", (1, 1.5, 2, 3, 4, 6)),
            ("z10", "10 hPa 고도 편차 (m)", "polar", (25, 50, 75, 100, 150, 200)),
            ("t850", "850 hPa 기온 편차 (°C)", "polar", (0.5, 1, 1.5, 2, 3)),
            ("u250", "250 hPa 동서풍 편차 (m/s)", "polar", (1, 2, 3, 4, 6)),
            ("sst", "해수면온도 편차 (°C)", "pacific", (0.25, 0.5, 0.75, 1))]
    fig = plt.figure(figsize=(15, 9.5))
    stats = {}
    for i, (name, title, kind, steps) in enumerate(spec):
        da = window_anom(name, start, end)
        if kind == "polar":
            ax = fig.add_subplot(2, 3, i + 1, projection=ccrs.NorthPolarStereo(central_longitude=120))
            ax.set_extent([-180, 180, 20, 90], ccrs.PlateCarree())
            da = da.sel(lat=slice(15, 90))
        elif kind == "eurasia":
            ax = fig.add_subplot(2, 3, i + 1, projection=ccrs.PlateCarree(central_longitude=110))
            ax.set_extent([0, 220, 5, 85], ccrs.PlateCarree())
            ax.set_aspect("auto")
        else:
            ax = fig.add_subplot(2, 3, i + 1, projection=ccrs.PlateCarree(central_longitude=180))
            ax.set_extent([30, 290, -30, 65], ccrs.PlateCarree())
            ax.set_aspect("auto")
        lev = _levels(da, steps)
        cf = ax.contourf(*np.meshgrid(_cyclic(da).lon, da.lat), _cyclic(da).values, levels=lev, cmap=cmap,
                         extend="both", transform=ccrs.PlateCarree())
        ax.coastlines(linewidth=0.5, color="#474747")
        ax.gridlines(linewidth=0.3, color="#c2c2c2")
        box = {"z500": "ural", "sst": "nino34"}.get(name)
        if box:
            s, n, w, e = C.REGIONS[box]
            xs = np.r_[np.linspace(w, e, 30), np.full(30, e), np.linspace(e, w, 30), np.full(30, w)]
            ys = np.r_[np.full(30, s), np.linspace(s, n, 30), np.full(30, n), np.linspace(n, s, 30)]
            ax.plot(xs, ys, color=INK2, lw=1.2, transform=ccrs.PlateCarree())
        ax.plot(127.5, 36, marker="*", ms=9, color="#191919", mec="white", mew=0.6, transform=ccrs.PlateCarree())
        ax.set_title(title, fontsize=11, loc="left")
        fig.colorbar(cf, ax=ax, orientation="horizontal", pad=0.04, shrink=0.85, aspect=35)
        stats[name] = dict(min=float(da.min()), max=float(da.max()))
    fig.suptitle(f"북반구 편차장 ({start} ~ {end} 평균, 평년 {C.CLIM[0]}~{C.CLIM[1]}) · ★ 한반도, 상자: 우랄 영역·Niño3.4",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig01_anomaly_maps.png")
    return stats


def plot_ea_maps(start, end) -> dict:
    """동아시아(20~55°N, 100~150°E) 기온·강수 편차와 하위 영역 평균."""
    plt = setup_plot()
    import cartopy.crs as ccrs
    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(12, 5.4))
    out = {}
    for i, (name, title, steps, cmap) in enumerate((("t2m", "2 m 기온 편차 (°C)", (0.5, 1, 1.5, 2, 3), diverging_cmap()),
                                                    ("tp", "강수 편차 (mm/일)", (0.25, 0.5, 1, 1.5, 2), diverging_cmap().reversed()))):
        da = window_anom(name, start, end).sel(lat=slice(C.EA_BOX[0], C.EA_BOX[1]), lon=slice(C.EA_BOX[2], C.EA_BOX[3]))
        ax = fig.add_subplot(1, 2, i + 1, projection=pc)
        ax.set_extent([C.EA_BOX[2], C.EA_BOX[3], C.EA_BOX[0], C.EA_BOX[1]], pc)
        cf = ax.contourf(da.lon, da.lat, da.values, levels=_levels(da, steps), cmap=cmap, extend="both", transform=pc)
        ax.coastlines(linewidth=0.6, color="#474747")
        for key, (label, (s, n, w, e)) in C.EA_SUBREGIONS.items():
            if key == "ea":
                continue
            ax.plot([w, e, e, w, w], [s, s, n, n, s], color=INK2, lw=1, transform=pc)
        ax.set_title(title, fontsize=11, loc="left")
        fig.colorbar(cf, ax=ax, orientation="horizontal", pad=0.06, shrink=0.85, aspect=35)
        out[name] = dict(min=float(da.min()), max=float(da.max()))
    fig.suptitle(f"동아시아 기온·강수 편차 ({start} ~ {end}) · 상자: 하위 영역(한반도, 중국 북부·남부, 일본, 몽골·시베리아 남부)",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    savefig(fig, "fig14_east_asia_maps.png")
    return out


def plot_daily(df: pd.DataFrame, start, end, back: int = 90) -> None:
    """한반도 기온·강수와 주요 지수의 일별 시계열 (변수마다 따로 축을 둔다)."""
    plt = setup_plot()
    t0 = pd.Timestamp(end) - pd.Timedelta(days=back - 1)
    d = df[t0:end]
    panels = ["korea_t", "korea_p", "ural", "u1060", "ao", "siberian_high", "eawm", "nino34"]
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 15), sharex=True)
    for ax, key in zip(axes, panels):
        if key == "u1060":
            ax.plot(d.index, d[key], color=BLUE, lw=2, label="관측")
            ax.plot(d.index, series_clim(df[key])[t0:end], color=INK2, lw=1, ls="--", label="평년")
            ax.axhline(0, color="#c2c2c2", lw=1)
            ax.legend(frameon=False, ncol=2, fontsize=9, loc="upper left")
            ax.set_title("10 hPa 60°N 동서평균 동서풍 (m/s) · 0 아래로 내려가면 돌연승온", fontsize=10, loc="left")
        elif key in ("korea_t", "korea_p"):
            pos, neg = (WARM, COOL) if key == "korea_t" else (COOL, ORANGE)     # 강수는 많음=파랑, 적음=주황
            ax.bar(d.index, d[key], width=0.8, color=np.where(d[key] >= 0, pos, neg))
            ax.axhline(0, color="#c2c2c2", lw=1)
            ax.set_title(f"{INDEX_LABEL[key][0]} ({INDEX_LABEL[key][1]})", fontsize=10, loc="left")
        else:
            ax.plot(d.index, d[key], color=BLUE, lw=2)
            ax.axhline(0, color="#c2c2c2", lw=1)
            ttl = f"{INDEX_LABEL[key][0]} ({INDEX_LABEL[key][1]})"
            if key == "ural":
                blk = d["blocked"].values.astype(bool)
                ax.fill_between(d.index, 0, 1, where=blk, transform=ax.get_xaxis_transform(),
                                color=ORANGE, alpha=0.18, lw=0)
                ttl += " · 주황 바탕: 30~90°E 블로킹일(역전 지수)"
            ax.set_title(ttl, fontsize=10, loc="left")
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(hours=12), color="#000000", alpha=0.04, lw=0)
    axes[0].annotate("회색 바탕: 분석 대상 30일", xy=(1, 1.02), xycoords="axes fraction", ha="right",
                     va="bottom", fontsize=9, color=INK2)
    fig.tight_layout()
    savefig(fig, "fig02_daily_series.png")


def plot_waf(start, end) -> None:
    from . import dynamics
    plt = setup_plot()
    import cartopy.crs as ccrs
    w = dynamics.tn_flux(start, end)
    fig = plt.figure(figsize=(11, 5.2))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree(central_longitude=100))
    ax.set_extent([-20, 200, 20, 85], ccrs.PlateCarree())
    ax.set_aspect("auto")
    za = w.za.sel(lat=slice(15, 88))
    cf = ax.contourf(*np.meshgrid(_cyclic(za).lon, za.lat), _cyclic(za).values,
                     levels=_levels(za, (20, 30, 40, 60, 80)), cmap=diverging_cmap(), extend="both",
                     transform=ccrs.PlateCarree())
    sub = w.sel(lat=slice(21, 84)).isel(lat=slice(None, None, 2), lon=slice(None, None, 3))
    mag = np.hypot(sub.fx, sub.fy)
    thr = float(np.nanpercentile(mag, 60))
    fx, fy = sub.fx.where(mag >= thr), sub.fy.where(mag >= thr)
    q = ax.quiver(sub.lon.values, sub.lat.values, fx.values, fy.values, transform=ccrs.PlateCarree(),
                  scale=float(np.nanpercentile(mag, 99)) * 18, width=0.0022, color="#191919")
    ref = float(np.nanpercentile(mag, 97))
    ax.quiverkey(q, 0.9, 1.04, ref, f"{ref:.0f} m²/s²", labelpos="E", fontproperties={"size": 9})
    ax.coastlines(linewidth=0.5, color="#474747")
    ax.plot(127.5, 36, marker="*", ms=10, color="#191919", mec="white", mew=0.6, transform=ccrs.PlateCarree())
    fig.colorbar(cf, ax=ax, orientation="horizontal", pad=0.06, shrink=0.7, aspect=40, label="250 hPa 고도 편차 (m)")
    ax.set_title(f"250 hPa 파동활동 플럭스 (Takaya-Nakamura) · {start} ~ {end}", fontsize=11, loc="left")
    savefig(fig, "fig03_wave_activity_flux.png")


def plot_low_level(start, end) -> dict:
    from . import dynamics
    plt = setup_plot()
    import cartopy.crs as ccrs
    d = dynamics.low_level(start, end)
    fig = plt.figure(figsize=(13, 5.6))
    pc = ccrs.PlateCarree()
    sk = dict(lat=slice(None, None, 2), lon=slice(None, None, 2))
    panels = [("adv_anom", "850 hPa 온도 이류 편차 (K/일) · 화살표: 바람 편차", "u_anom", "v_anom", (0.5, 1, 1.5, 2), "m/s"),
              ("q_anom", "850 hPa 비습 편차 (g/kg) · 화살표: 수증기 수송(q·V) 편차", "qu_anom", "qv_anom",
               (0.2, 0.3, 0.5, 0.75, 1), "g/kg·m/s")]
    for i, (shade, title, uu, vv, steps, unit) in enumerate(panels):
        ax = fig.add_subplot(1, 2, i + 1, projection=pc)
        ax.set_extent([90, 160, 15, 60], pc)
        ax.set_aspect("auto")
        cf = ax.contourf(d.lon, d.lat, d[shade], levels=_levels(d[shade].sel(lat=slice(15, 60), lon=slice(90, 160)), steps),
                         cmap=diverging_cmap(), extend="both", transform=pc)
        s = d.isel(**sk)
        mag = np.hypot(s[uu], s[vv]).sel(lat=slice(15, 60), lon=slice(90, 160))
        ref = float(np.nanpercentile(mag, 90))
        q = ax.quiver(s.lon.values, s.lat.values, s[uu].values, s[vv].values, transform=pc,
                      scale=ref * 22, width=0.003, color="#191919")
        ax.quiverkey(q, 0.74, 1.04, ref, f"{ref:.1f} {unit}", labelpos="E", fontproperties={"size": 9})
        ax.coastlines(linewidth=0.6, color="#474747")
        ax.plot(127.5, 36, marker="*", ms=10, color="#191919", mec="white", mew=0.6, transform=pc)
        ax.set_title(title, fontsize=10.5, loc="left")
        fig.colorbar(cf, ax=ax, orientation="horizontal", pad=0.06, shrink=0.8, aspect=35)
    fig.tight_layout()
    savefig(fig, "fig04_low_level.png")
    k = d.sel(lat=slice(*C.REGIONS["korea"][:2]), lon=slice(*C.REGIONS["korea"][2:])).mean()
    return {v: float(k[v]) for v in ("adv_anom", "adv", "qu_anom", "qv_anom", "u_anom", "v_anom", "q_anom")}


def plot_pch(end, back: int = 150) -> None:
    """극관 고도 표준화 편차의 연직-시간 단면 (성층권 편차의 하향 전파 여부)."""
    plt = setup_plot()
    pch = xr.open_dataarray(C.DATA / "derived" / "pch.nc")
    t0 = pd.Timestamp(end) - pd.Timedelta(days=back - 1)
    p = pch.sel(time=slice(t0, pd.Timestamp(end)))
    fig, ax = plt.subplots(figsize=(11, 3.8))
    cf = ax.contourf(p.time.values, p.level.values, p.values.T, levels=np.arange(-3, 3.01, 0.5),
                     cmap=diverging_cmap(), extend="both")
    ax.set_yscale("log")
    ax.invert_yaxis()
    ax.set_yticks([10, 30, 100, 300, 1000], labels=["10", "30", "100", "300", "1000"])
    ax.set_ylabel("기압 (hPa)")
    ax.grid(False)
    fig.colorbar(cf, ax=ax, pad=0.01, label="표준화 편차 (σ)")
    ax.set_title("극관(65°N 이북) 평균 고도 편차 · 양(+)은 약한 극소용돌이", fontsize=11, loc="left")
    savefig(fig, "fig05_polar_cap_height.png")


def summarize(df: pd.DataFrame, start, end) -> dict:
    """분석 기간의 지수 평균, 같은 기간 과거 값 대비 표준화 값과 순위."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    rows = {}
    for key in ["korea_t", "korea_p", "ural", "pv", "u1060", "pch10", "pch500", "nino34", "ao", "siberian_high",
                "ea_jet", "eawm", "phil_sea", "bk_ice"]:
        hist = same_season_windows(df[key], start, end)
        now = float(hist.iloc[-1])
        base = hist[(hist.index >= C.CLIM[0]) & (hist.index <= C.CLIM[1])]
        rows[key] = dict(mean=now, z=float((now - base.mean()) / base.std()),
                         rank_high=int((hist > now).sum() + 1), n_years=int(len(hist)))
    w = df[start:end]
    p_tot, p_norm = float(w["korea_p_raw"].sum()), float(w["korea_p_clim"].sum())
    out = dict(start=str(start.date()), end=str(end.date()), indices=rows,
               korea=dict(t_mean=float(w["korea_t_raw"].mean()), t_anom=float(w["korea_t"].mean()),
                          p_total=p_tot, p_normal=p_norm, p_ratio=p_tot / p_norm * 100,
                          t_anom_min=float(w["korea_t"].min()), t_anom_min_date=str(w["korea_t"].idxmin().date()),
                          t_anom_max=float(w["korea_t"].max()), t_anom_max_date=str(w["korea_t"].idxmax().date()),
                          cold_days=int((w["korea_t"] < 0).sum()), n_days=int(len(w))),
               blocked_days=int(w["blocked"].sum()), u1060_min=float(w["u1060"].min()),
               u1060_min_date=str(w["u1060"].idxmin().date()),
               u1060_clim=float(series_clim(df["u1060"])[start:end].mean()))
    if "asos_t" in df and w["asos_t"].notna().all():
        out["asos"] = dict(t_anom=float(w["asos_t"].mean()), p_anom=float(w["asos_p"].mean()),
                           corr_t=float(df["asos_t"].corr(df["korea_t"])), corr_p=float(df["asos_p"].corr(df["korea_p"])))
    return out


def run(start, end) -> dict:
    df = load_indices()
    out = summarize(df, start, end)
    out["map_range"] = plot_maps(start, end)
    out["ea_map_range"] = plot_ea_maps(start, end)
    plot_daily(df, start, end)
    plot_waf(start, end)
    out["korea_low_level"] = plot_low_level(start, end)
    plot_pch(end)
    (C.OUT / "recent_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info("진단 완료: 한반도 기온 편차 %+.2f°C, 강수 평년비 %.0f%%", out["korea"]["t_anom"], out["korea"]["p_ratio"])
    return out
