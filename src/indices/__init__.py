"""2단계: 일별 지수 계산. 사건(블로킹, SSW) 날짜는 자료에서 탐지한다."""
from __future__ import annotations

import pandas as pd
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, get_logger, open_field

log = get_logger("indices")


def run() -> pd.DataFrame:
    from . import blocking, circulation, enso, korea, strat, teleconnections
    C.OUT.mkdir(exist_ok=True)
    z500 = open_field("z500").load()
    ub, ub_events = blocking.compute(z500)
    log.info("우랄블로킹 사건 %d건 (5일 이상)", len(ub_events))
    st, ssw, pch = strat.compute(xr.open_dataset(C.DATA / "merged" / "strat.nc").load())
    log.info("SSW %d건", len(ssw))
    n34, oni = enso.compute(open_field("sst").load())
    circ = circulation.compute(open_field("msl").load(), open_field("u200").load(),
                               open_field("u300").load(), open_field("ci").load())
    t2m, tp = open_field("t2m").load(), open_field("tp").load()
    kor = korea.compute(t2m, tp)
    ea = korea.ea_regions(t2m, tp)
    tele, tele_meta, tele_pat = teleconnections.compute(z500)
    teleconnections.save_meta(tele_meta)
    atomic_to_netcdf(tele_pat.to_dataset(), C.DATA / "derived" / "tele_patterns.nc")
    z10 = open_field("z10").load()
    st2 = pd.concat([strat.polar_cap_t10(open_field("t10").load()),
                     strat.eddy_heat_flux(open_field("v100").load(), open_field("t100").load()),
                     strat.wave_amplitude(z10), strat.vortex_geometry(z10)], axis=1)
    from ..common import series_anom
    st2["t10_cap_anom"] = series_anom(st2["t10_cap"])
    st2["vt100_anom"] = series_anom(st2["vt100"])
    aleut = circulation.aleutian(open_field("msl").load())
    df = pd.concat([kor, ea, ub, st, st2, n34, circ, aleut, tele], axis=1)
    df["blocked"] = df["blocked"].astype(int)
    df.index.name = "date"
    df.round(4).to_csv(C.OUT / "indices_daily.csv")
    ub_events.to_csv(C.OUT / "events_ural_blocking.csv", index=False)
    ssw.to_csv(C.OUT / "events_ssw.csv", index=False)
    oni.to_csv(C.OUT / "oni_monthly.csv")
    enso.winter_phase(oni["oni"]).to_csv(C.OUT / "enso_winters.csv", index=False)
    atomic_to_netcdf(pch.to_dataset(), C.DATA / "derived" / "pch.nc")
    log.info("지수 %d일 x %d열 저장 (%s ~ %s)", len(df), df.shape[1], df.index[0].date(), df.index[-1].date())
    return df
