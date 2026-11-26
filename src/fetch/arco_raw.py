"""Google ARCO-ERA5 원시 파일(익명 공개)에서 2023년 이후 일자료를 만든다.

Zarr 저장소는 기압면 한 시각이 37층 전구 한 덩어리(약 118 MB)라 한 층만 읽기에는 너무 무겁다.
같은 버킷의 원시 netCDF(날짜/변수/기압면별 파일)를 필요한 만큼만 읽는다.

- 2026-02 이전 파일: 압축 없는 netCDF3 → 머리말을 해석해 필요한 시각·위도 줄만 바이트 범위로 읽는다.
- 그 뒤 파일: 압축된 netCDF4(HDF5) → h5py로 필요한 청크만 읽는다.
  (형식은 날짜가 아니라 파일 첫 바이트로 가린다.)

기압면·해면기압은 00/06/12/18 UTC 평균, 기온·강수는 24시각 평균·합, 해수면온도·해빙은 00 UTC.
0.25° 자료를 WeatherBench2와 같은 1.5° 격자로 상자 평균해 하루 한 파일로 저장한다.
"""
from __future__ import annotations

import datetime as dt
import struct
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr

from .. import config as C
from ..common import atomic_to_netcdf, box_regrid, box_weights_lat, box_weights_lon, get_logger

log = get_logger("fetch.arco")

NLAT, NLON = 721, 1440
LAT_SRC = 90.0 - 0.25 * np.arange(NLAT)
LON_SRC = 0.25 * np.arange(NLON)
H6 = (0, 6, 12, 18)
H24 = tuple(range(24))
HEAD = 4096


def _rows(lat_lo: float, lat_hi: float) -> tuple[int, int]:
    """목표 위도 범위(±0.75° 상자 포함)를 덮는 원자료 줄 번호 (북→남 순서)."""
    r0 = int(round((90.0 - min(lat_hi + 0.75, 90.0)) / 0.25))
    r1 = int(round((90.0 - max(lat_lo - 0.75, -90.0)) / 0.25))
    return r0, r1


def _cols(lon_lo: float, lon_hi: float) -> tuple[int, int]:
    return int(round((lon_lo - 0.75) / 0.25)), int(round((lon_hi + 0.75) / 0.25))


EA_LAT_T = np.arange(C.EA_LAT[0], C.EA_LAT[1] + 0.1, 1.5)
EA_LON_T = np.arange(C.EA_LON[0], C.EA_LON[1] + 0.1, 1.5)
CAP_LAT_T = C.LAT_NH[C.LAT_NH >= C.PCAP_LAT]


@dataclass(frozen=True)
class Item:
    key: str            # 결과 이름
    path: str           # 날짜 폴더 아래 경로
    hours: tuple
    rows: tuple         # (r0, r1) 포함
    kind: str           # nh | sst | ea | cap | u60
    cols: tuple = (0, NLON - 1)


def items() -> list[Item]:
    out = []
    nh = (0, 360)   # 90°N~적도. 적도 줄은 북쪽 반 상자만 평균한다 (HDF5 청크 경계를 넘지 않게)
    for name, (var, lev) in C.PL_FIELDS.items():
        out.append(Item(name, f"PL/{var}/{lev}.nc", H6, nh, "nh"))
    out.append(Item("z10", "PL/geopotential/10.nc", H6, nh, "nh"))
    field_levs = {500, 250, 10}
    for lev in C.PCAP_LEVELS:
        if lev not in field_levs:
            out.append(Item(f"cap{lev}", f"PL/geopotential/{lev}.nc", H6, _rows(CAP_LAT_T[0], 90), "cap"))
    out.append(Item("u1060", "PL/u_component_of_wind/10.nc", H6, (120, 120), "u60"))
    s = C.SFC_FIELDS
    out.append(Item("msl", f"SL/{s['msl']}/surface.nc", H6, nh, "nh"))
    ea_rows, ea_cols = _rows(*C.EA_LAT), _cols(*C.EA_LON)
    out.append(Item("t2m", f"SL/{s['t2m']}/surface.nc", H24, ea_rows, "ea", ea_cols))
    out.append(Item("tp", f"SL/{s['tp']}/surface.nc", H24, ea_rows, "ea", ea_cols))
    out.append(Item("sst", f"SL/{s['sst']}/surface.nc", (0,), _rows(C.LAT_SST[0], 90), "sst"))
    out.append(Item("ci", f"SL/{s['ci']}/surface.nc", (0,), nh, "nh"))
    return out


def _path(date: dt.date, it: Item) -> str:
    kind, rest = it.path.split("/", 1)
    base = C.GARCO_RAW_PL if kind == "PL" else C.GARCO_RAW_SL
    return f"{base}/{date:%Y/%m/%d}/{rest}"


# ------------------------------------------------------------------ netCDF3 머리말 해석
_NC_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
_NC_FMT = {1: "b", 2: "c", 3: "h", 4: "i", 5: "f", 6: "d"}


def parse_cdf_header(b: bytes) -> dict:
    """netCDF3(classic/64-bit offset) 머리말에서 자료 변수의 위치와 포장 계수를 꺼낸다."""
    assert b[:3] == b"CDF" and b[3] in (1, 2), "netCDF3 형식이 아님"
    big = b[3] == 2
    pos = 4

    def u32():
        nonlocal pos
        v = struct.unpack(">I", b[pos:pos + 4])[0]
        pos += 4
        return v

    def name():
        nonlocal pos
        n = u32()
        s = b[pos:pos + n].decode()
        pos += (n + 3) // 4 * 4
        return s

    def atts():
        nonlocal pos
        tag, n = u32(), u32()
        out = {}
        for _ in range(n):
            k = name()
            typ, cnt = u32(), u32()
            size = _NC_SIZE[typ] * cnt
            raw = b[pos:pos + size]
            pos += (size + 3) // 4 * 4
            out[k] = raw.decode(errors="replace") if typ == 2 else \
                struct.unpack(f">{cnt}{_NC_FMT[typ]}", raw)
        return out

    numrecs = u32()
    tag, ndim = u32(), u32()
    dims = [(name(), u32()) for _ in range(ndim)]
    atts()
    tag, nvar = u32(), u32()
    var = {}
    for _ in range(nvar):
        vn = name()
        nd = u32()
        dimids = [u32() for _ in range(nd)]
        a = atts()
        typ, vsize = u32(), u32()
        if big:
            begin = struct.unpack(">Q", b[pos:pos + 8])[0]
            pos += 8
        else:
            begin = u32()
        var[vn] = dict(dims=[dims[i] for i in dimids], atts=a, type=typ, begin=begin)
    data = [v for v in var.values() if len(v["dims"]) == 3]
    assert len(data) == 1 and numrecs == 0, "예상과 다른 파일 구조"
    v = data[0]
    assert [n for _, n in v["dims"]] == [24, NLAT, NLON] and v["type"] == 3, "예상과 다른 차원/자료형"
    return dict(begin=v["begin"], scale=v["atts"]["scale_factor"][0], offset=v["atts"]["add_offset"][0],
                fill=v["atts"].get("_FillValue", (None,))[0])


# ------------------------------------------------------------------ 읽기
def _read_cdf(fs, paths: list[str], its: list[Item], heads: list[bytes]) -> list[np.ndarray]:
    """netCDF3 파일들에서 (시각, 줄 범위) 블록을 한꺼번에 범위 읽기."""
    meta = [parse_cdf_header(h) for h in heads]
    rp, rs, re_, owner = [], [], [], []
    for i, (p, it, m) in enumerate(zip(paths, its, meta)):
        r0, r1 = it.rows
        for h in it.hours:
            s = m["begin"] + (h * NLAT + r0) * NLON * 2
            rp.append(p); rs.append(s); re_.append(s + (r1 - r0 + 1) * NLON * 2); owner.append(i)
    blobs = fs.cat_ranges(rp, rs, re_)
    out = [[] for _ in its]
    for i, blob in zip(owner, blobs):
        if isinstance(blob, Exception):
            raise blob
        it, m = its[i], meta[i]
        raw = np.frombuffer(blob, dtype=">i2").reshape(-1, NLON)
        a = raw.astype("float32") * np.float32(m["scale"]) + np.float32(m["offset"])
        if m["fill"] is not None:
            a[raw == m["fill"]] = np.nan
        out[i].append(a[:, it.cols[0]:it.cols[1] + 1])
    return [np.stack(x) for x in out]


def _read_hdf(blob: bytes, it: Item) -> np.ndarray:
    """통째로 받은 netCDF4(HDF5) 파일에서 필요한 시각·줄·칸만 푼다."""
    import io

    import h5py
    with h5py.File(io.BytesIO(blob), "r") as h:
        d = [v for v in h.values() if isinstance(v, h5py.Dataset) and v.ndim >= 3][0]
        assert d.shape[0] == 24 and d.shape[-2:] == (NLAT, NLON), "예상과 다른 차원"
        hrs = list(it.hours) if len(it.hours) < 24 else slice(None)
        rs = slice(it.rows[0], it.rows[1] + 1)
        cs = slice(it.cols[0], it.cols[1] + 1)
        a = d[hrs, 0, rs, cs] if d.ndim == 4 else d[hrs, rs, cs]
    return np.asarray(a, dtype="float32")


# ------------------------------------------------------------------ 0.25° → 1.5° 일값
_W: dict = {}


def _weights(it: Item, tgt_lat: np.ndarray, tgt_lon: np.ndarray):
    k = (it.rows, it.cols, tgt_lat.size, tgt_lon.size)
    if k not in _W:
        _W[k] = (box_weights_lat(LAT_SRC[it.rows[0]:it.rows[1] + 1], tgt_lat),
                 box_weights_lon(LON_SRC[it.cols[0]:it.cols[1] + 1], tgt_lon))
    return _W[k]


def _cap_mean(zm_lat: np.ndarray, lat_src: np.ndarray) -> float:
    """동서평균 고도(위도 줄)를 1.5° 위도로 묶은 뒤 65°N 이북을 cos 가중 평균 (WB2 쪽 정의와 같게)."""
    w = box_weights_lat(lat_src, CAP_LAT_T)
    return float(np.average(w @ zm_lat, weights=np.cos(np.deg2rad(CAP_LAT_T))))


def reduce_day(arrs: dict[str, np.ndarray], its: list[Item]) -> xr.Dataset:
    """항목별 (시각, 줄, 칸) 배열을 일값으로 줄인다. ECMWF ARCO 경로도 같은 함수를 쓴다."""
    ds = xr.Dataset()
    cap = {}
    for it in its:
        a = arrs[it.key]
        if it.kind == "u60":
            ds["u1060"] = float(a.mean())
        elif it.kind == "cap":
            cap[int(it.key[3:])] = _cap_mean(a.mean((0, 2)) / C.G, LAT_SRC[it.rows[0]:it.rows[1] + 1])
        elif it.kind == "ea":
            day = a.sum(0) * 1000.0 if it.key == "tp" else a.mean(0)
            ds[it.key] = (("lat_ea", "lon_ea"), box_regrid(day, *_weights(it, EA_LAT_T, EA_LON_T)))
        else:
            tgt = C.LAT_SST if it.kind == "sst" else C.LAT_NH
            day = a.mean(0)
            if it.key.startswith("z"):
                day = day / C.G
                lev = int(it.key[1:])
                if lev in C.PCAP_LEVELS:
                    r = slice(0, _rows(CAP_LAT_T[0], 90)[1] + 1)
                    cap[lev] = _cap_mean(day[r].mean(1), LAT_SRC[r])
            elif it.key == "msl":
                day = day / 100.0
            dims = ("lat_sst", "lon") if it.kind == "sst" else ("lat", "lon")
            ds[it.key] = (dims, box_regrid(day, *_weights(it, tgt, C.LON)))
    ds["pcap"] = ("level", np.array([cap[l] for l in C.PCAP_LEVELS], dtype="float32"))
    return ds.assign_coords(lat=C.LAT_NH, lon=C.LON, lat_sst=C.LAT_SST, lat_ea=EA_LAT_T,
                            lon_ea=EA_LON_T, level=C.PCAP_LEVELS)


# ------------------------------------------------------------------ 하루 단위 작업
def day_path(date: dt.date) -> Path:
    return C.DATA / "arco" / f"{date:%Y}" / f"{date:%Y%m%d}.nc"


_FS = None


def _fs():
    global _FS
    if _FS is None:
        import gcsfs
        _FS = gcsfs.GCSFileSystem(token="anon")
    return _FS


def fetch_day(date: dt.date) -> str:
    out = day_path(date)
    if out.exists():
        return "skip"
    fs = _fs()
    its = items()
    paths = [_path(date, it) for it in its]
    heads = fs.cat_ranges(paths, 0, HEAD)
    for p, h in zip(paths, heads):
        if isinstance(h, Exception):
            raise RuntimeError(f"{p}: {h!r}")
    is_cdf = [h[:3] == b"CDF" for h in heads]
    arrs = {}
    ci = [i for i, c in enumerate(is_cdf) if c]
    if ci:
        got = _read_cdf(fs, [paths[i] for i in ci], [its[i] for i in ci], [heads[i] for i in ci])
        arrs.update({its[i].key: g for i, g in zip(ci, got)})
    hi = [i for i, c in enumerate(is_cdf) if not c]
    for k in range(0, len(hi), 8):        # 압축 파일은 8개씩 통째로 받아 메모리에서 푼다
        part = hi[k:k + 8]
        blobs = fs.cat_ranges([paths[i] for i in part], None, None)
        for i, blob in zip(part, blobs):
            if isinstance(blob, Exception):
                raise RuntimeError(f"{paths[i]}: {blob!r}")
            arrs[its[i].key] = _read_hdf(blob, its[i])
    ds = reduce_day(arrs, its).expand_dims(time=[np.datetime64(date, "ns")])
    atomic_to_netcdf(ds, out)
    return "ok"


def latest_complete_date(today: dt.date | None = None, max_back: int = 20) -> dt.date:
    """필요한 파일이 모두 올라온 가장 최근 날짜를 저장소에서 찾는다."""
    fs = _fs()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    its = items()
    for back in range(3, max_back):
        d = today - dt.timedelta(days=back)
        try:
            ok = all(not isinstance(h, Exception) and len(h) > 0
                     for h in fs.cat_ranges([_path(d, it) for it in its], 0, 8))
        except Exception:
            ok = False
        if ok:
            return d
    raise RuntimeError("최근 20일 안에 완결된 ARCO-ERA5 원시 자료가 없다")


def run(end: dt.date, workers: int = 6) -> None:
    start = dt.date.fromisoformat(C.ARCO_FIRST)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in days if not day_path(d).exists()]
    log.info("ARCO-ERA5 원시 자료: 전체 %d일 중 %d일 받을 예정", len(days), len(todo))
    if not todo:
        return
    failed = []
    import multiprocessing as mp
    with ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(fetch_day, d): d for d in todo}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as e:  # 한 날짜가 실패해도 나머지는 계속 받는다
                failed.append(futs[f])
                log.warning("%s 실패: %r", futs[f], e)
            if n % 50 == 0 or n == len(todo):
                log.info("ARCO %d/%d", n, len(todo))
    if failed:
        raise RuntimeError(f"{len(failed)}일을 받지 못했다. 다시 실행하면 이어받는다: {sorted(failed)[:5]} ...")


if __name__ == "__main__":
    import sys
    run(dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else latest_complete_date())
