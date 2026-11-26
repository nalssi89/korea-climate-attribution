"""전체 흐름: fetch → indices → diagnose → attribute → forcing → report → site.

    python -m src.run                    # 받을 수 있는 가장 최근 날짜까지
    python -m src.run --end 2026-11-18   # 끝 날짜 지정 (그날까지 30일을 분석)
    python -m src.run --skip-fetch       # 이미 받은 자료로 계산·보고서만 다시
    python -m src.run --skip-fetch --steps forcing,report,site   # 강제인자 분석만 다시

마지막 단계(site)가 대시보드와 모식도가 읽는 site/data/를 갱신한다.
"""
from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd
import xarray as xr

from . import config as C
from .common import get_logger

log = get_logger("run")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=None, help="분석 기간의 끝 날짜 (YYYY-MM-DD)")
    ap.add_argument("--skip-fetch", action="store_true", help="내려받기를 건너뛰고 병합된 자료를 그대로 쓴다")
    ap.add_argument("--steps", default="indices,diagnose,attribute,forcing,report,site", help="실행할 단계 (쉼표로 구분)")
    args = ap.parse_args()
    steps = args.steps.split(",")

    if args.skip_fetch:
        with xr.open_dataset(C.DATA / "merged" / "z500.nc") as ds:
            data_end = pd.Timestamp(ds.time.values[-1]).date()
    else:
        from . import fetch
        data_end = fetch.run(args.end)
    end = min(args.end, data_end) if args.end else data_end
    start = end - dt.timedelta(days=C.WINDOW_DAYS - 1)
    log.info("분석 기간: %s ~ %s (자료 끝 %s)", start, end, data_end)

    if "indices" in steps:
        from . import indices
        indices.run()
    import numpy as np
    from .common import load_indices
    case = None
    if "diagnose" in steps:
        from . import diagnose
        from .diagnose import ssw
        diagnose.run(start, end)
        case = ssw.analyze(load_indices(), end, np.random.default_rng(C.SEED))
    att = None
    if "attribute" in steps:
        from . import attribute
        att = attribute.run(end)
    if "forcing" in steps:
        from . import forcing
        forcing.run(end)
    if "report" in steps:
        from . import report
        path = report.run()
        log.info("보고서: %s", path)
    if "site" in steps:
        import json
        from . import export
        df = load_indices()
        if att is None:
            from . import attribute
            att = dict(zip(("periods", "r2_by_kind"),
                           attribute.run_periods(df, pd.Timestamp(end), np.random.default_rng(C.SEED))))
        if case is None:
            case = json.loads((C.OUT / "ssw_case.json").read_text())
        export.run(end, att["periods"], att["r2_by_kind"], case, df)


if __name__ == "__main__":
    main()
