"""최근 겨울 사례: 겨울별로 세 인자(우랄블로킹, SSW, 엔소)와 한반도 기온·강수를 시간순으로 정리한다."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C


def recent_winters(end: pd.Timestamp, n: int = C.N_CASE_WINTERS) -> list[int]:
    """끝난 겨울(11~3월) 중 최근 n개의 시작 연도."""
    last = end.year - 1 if end >= pd.Timestamp(end.year, 3, 31) else end.year - 2
    return list(range(last - n + 1, last + 1))


def winter_summary(df: pd.DataFrame, y: int, ub: pd.DataFrame, ssw: pd.DataFrame, oni: pd.DataFrame) -> dict:
    name = f"{y}/{str(y + 1)[2:]}"
    djf = df[f"{y}-12-01":f"{y + 1}-02-28"]
    ext = df[f"{y}-11-01":f"{y + 1}-03-31"]
    o = oni["oni"].get(pd.Timestamp(y + 1, 1, 1), np.nan)
    phase = "엘니뇨" if o >= C.ONI_THRESHOLD else ("라니냐" if o <= -C.ONI_THRESHOLD else "중립")
    events = []
    ub = ub.assign(onset=pd.to_datetime(ub.onset), end=pd.to_datetime(ub.end))
    for _, e in ub[(ub.onset >= ext.index[0]) & (ub.onset <= ext.index[-1])].iterrows():
        after = df.loc[e.onset + pd.Timedelta(days=3):e.onset + pd.Timedelta(days=12), "korea_t"]
        events.append(dict(date=str(e.onset.date()), kind="우랄블로킹", end=str(e.end.date()),
                           duration=int(e.duration), max_anom=float(e.max_anom),
                           korea_t_after=float(after.mean()), korea_t_min=float(after.min())))
    if len(ssw):
        sw = ssw.assign(date=pd.to_datetime(ssw.date))
        for _, e in sw[(sw.date >= ext.index[0]) & (sw.date <= ext.index[-1])].iterrows():
            a30 = df.loc[e.date:e.date + pd.Timedelta(days=30), "korea_t"]
            a60 = df.loc[e.date + pd.Timedelta(days=31):e.date + pd.Timedelta(days=60), "korea_t"]
            events.append(dict(date=str(e.date.date()), kind="SSW", min_u=float(e.min_u),
                               korea_t_0_30=float(a30.mean()), korea_t_31_60=float(a60.mean())))
    months = []
    for t in pd.date_range(f"{y}-11-01", f"{y + 1}-03-01", freq="MS"):
        m = df[t:t + pd.offsets.MonthEnd(0)]
        months.append(dict(month=f"{t.year}-{t.month:02d}", t_anom=float(m.korea_t.mean()),
                           p_ratio=float(m.korea_p_raw.sum() / m.korea_p_clim.sum() * 100),
                           ural=float(m.ural.mean()), blocked_days=int(m.blocked.sum()),
                           u1060=float(m.u1060.mean()), pv=float(m.pv.mean()), ao=float(m.ao.mean()),
                           nino34=float(m.nino34.mean()), siberian_high=float(m.siberian_high.mean())))
    return dict(winter=name, oni_djf=float(o), enso=phase,
                t_anom_djf=float(djf.korea_t.mean()),
                p_ratio_djf=float(djf.korea_p_raw.sum() / djf.korea_p_clim.sum() * 100),
                ao_djf=float(djf.ao.mean()), ural_djf=float(djf.ural.mean()),
                blocked_days=int(ext.blocked.sum()), u1060_min=float(ext.u1060.min()),
                u1060_min_date=str(ext.u1060.idxmin().date()),
                events=sorted(events, key=lambda e: e["date"]), months=months)
