"""공통 설정: 경로, 기간, 격자, 영역 정의."""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"            # 원자료 (git 제외)
OUT = ROOT / "outputs"          # 지수 시계열 등 작은 산출물 (커밋)
REPORTS = ROOT / "reports"      # 그림, 보고서 (커밋)

# ---------------------------------------------------------------- 기간
START_YEAR = 1979               # 과거 통계 시작
CLIM = (1991, 2020)             # 평년 기간
WB2_LAST_YEAR = 2022            # WeatherBench2 일평균을 쓰는 마지막 해
ARCO_FIRST = "2023-01-01"       # 이후는 ARCO-ERA5 (0.25° → 1.5°)
WB2_OVERLAP_END = "2023-01-09"  # 두 자료를 비교 검증하는 겹침 구간 끝
WINDOW_DAYS = 30                # "최근 한 달"
N_CASE_WINTERS = 3              # 사례 겨울 수

# ---------------------------------------------------------------- 자료 위치
WB2_DAILY = ("gs://weatherbench2/datasets/era5_daily/"
             "1959-2023_01_10-1h-240x121_equiangular_with_poles_conservative.zarr")
WB2_DAILY_37 = ("gs://weatherbench2/datasets/era5_daily/"
                "1959-2023_01_10-full_37-1h-512x256_equiangular_conservative.zarr")
GARCO_ZARR = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
GARCO_RAW_PL = "gcp-public-data-arco-era5/raw/date-variable-pressure_level"
GARCO_RAW_SL = "gcp-public-data-arco-era5/raw/date-variable-single_level"
ECMWF_ARCO = "https://arco.datastores.ecmwf.int"
KMA_HUB = "https://apihub.kma.go.kr"

# ---------------------------------------------------------------- 격자 (1.5°)
LON = np.arange(0.0, 360.0, 1.5)
LAT_NH = np.arange(0.0, 90.1, 1.5)          # 대기장: 적도~북극
LAT_SST = np.arange(-30.0, 90.1, 1.5)       # 해수면온도: 30°S~북극
EA_LAT = (21.0, 49.5)                       # 지상 기온·강수 저장 영역 (동아시아)
EA_LON = (99.0, 150.0)
G = 9.80665

# 극관 고도를 계산하는 기압면 (WB2 13층과 ARCO 37층의 공통층 + 10, 30 hPa)
PCAP_LEVELS = [10, 30, 50, 100, 150, 200, 250, 300, 500, 700, 850, 1000]
PCAP_LAT = 65.0

# 저장하는 2차원 장: 이름 -> (ERA5 변수, 기압면 또는 None)
PL_FIELDS = {
    "z500": ("geopotential", 500), "z250": ("geopotential", 250),
    "u200": ("u_component_of_wind", 200), "u250": ("u_component_of_wind", 250),
    "u300": ("u_component_of_wind", 300), "u850": ("u_component_of_wind", 850),
    "v250": ("v_component_of_wind", 250), "v850": ("v_component_of_wind", 850),
    "t850": ("temperature", 850), "q850": ("specific_humidity", 850),
}
SFC_FIELDS = {
    "msl": "mean_sea_level_pressure", "t2m": "2m_temperature",
    "tp": "total_precipitation", "sst": "sea_surface_temperature",
    "ci": "sea_ice_cover",
}
ALL_FIELDS = list(PL_FIELDS) + list(SFC_FIELDS) + ["z10"]

# ---------------------------------------------------------------- 지수 영역 (남, 북, 서, 동)
REGIONS = {
    "ural": (50, 70, 40, 80),            # 우랄블로킹 Z500 편차
    "ural_sector": (None, None, 30, 90),  # 블로킹 역전 지수 경도대
    "nino34": (-5, 5, 190, 240),
    "siberian_high": (40, 60, 80, 120),
    "ea_jet": (30, 35, 130, 160),        # Yang et al. (2002) U200
    "eawm_south": (27.5, 37.5, 110, 170),  # Jhun & Lee (2004) U300
    "eawm_north": (50, 60, 80, 140),
    "phil_sea": (10, 30, 120, 150),      # 필리핀해 고기압 (SLP 편차)
    "bk_ice": (65, 85, 30, 90),          # 바렌츠-카라 해빙 (Mori et al. 2014)
    "korea": (34.5, 37.5, 126, 129),     # 한반도(남한) 1.5° 격자 3x3, 육지 비율 가중
}

# ---------------------------------------------------------------- 사건 정의
BLOCK_MIN_DAYS = 5            # 지속 5일 이상
BLOCK_MIN_LON = 12.0          # 연속 12° 이상 경도가 막혀야 블로킹일
BLOCK_GHGN = -10.0            # m / 위도 1°
SSW_MONTHS = (11, 12, 1, 2, 3)
SSW_SEP_DAYS = 20             # 사건 사이 서풍 복귀 최소 일수
SSW_RETURN_DAYS = 10          # 최종승온 제외: 4월 말 전 서풍 10일 연속 복귀
ONI_THRESHOLD = 0.5
EXT_WINTER = (11, 12, 1, 2, 3)

# 회귀에 쓰는 원인 인자와 시차(일). 양수는 인자가 한반도보다 앞선다는 뜻.
DRIVERS = {
    "trend": 0,       # 장기 추세(연도)
    "ural": 5,        # 우랄 Z500 편차
    "pv": 15,         # 10 hPa 60°N 동서풍 편차 (극소용돌이 세기)
    "nino34": 0,      # Niño3.4
    "bk_ice": 30,     # 바렌츠-카라 해빙
}
N_BOOT = 1000
SEED = 20261126
