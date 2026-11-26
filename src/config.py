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
EA_LAT = (19.5, 55.5)                       # 지상 기온·강수 저장 영역 (동아시아 20~55°N을 덮는 1.5° 격자)
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
    # SSW 전조: 100 hPa 에디 열속 [v*T*] (45~75°N)
    "v100": ("v_component_of_wind", 100), "t100": ("temperature", 100),
}
SFC_FIELDS = {
    "msl": "mean_sea_level_pressure", "t2m": "2m_temperature",
    "tp": "total_precipitation", "sst": "sea_surface_temperature",
    "ci": "sea_ice_cover",
}
# z10, t10은 성층권 층이라 WB2 37층 자료(과거)와 ARCO 원시 자료(최근)에서 따로 받는다
STRAT_FIELDS = ["z10", "t10"]
ALL_FIELDS = list(PL_FIELDS) + list(SFC_FIELDS) + STRAT_FIELDS

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

# ---------------------------------------------------------------- 영향 평가 영역: 동아시아와 하위 영역 (남, 북, 서, 동)
EA_BOX = (20.0, 55.0, 100.0, 150.0)
EA_SUBREGIONS = {               # 이름 -> (한국어 이름, 영역). 모두 육지 비율로 가중한다.
    "korea": ("한반도", REGIONS["korea"]),
    "nchina": ("중국 북부", (34.5, 42.0, 109.5, 121.5)),
    "schina": ("중국 남부", (22.5, 30.0, 105.0, 120.0)),
    "japan": ("일본", (31.5, 40.5, 130.5, 141.0)),
    "mongolia": ("몽골·시베리아 남부", (45.0, 55.5, 90.0, 120.0)),
    "ea": ("동아시아 전체", EA_BOX),
}

# ---------------------------------------------------------------- 북반구 원격상관 패턴 (회전 EOF와 맞춰 볼 활동 중심)
# 각 패턴의 양(+)의 위상에서 Z500 편차의 부호: (위도, 경도, 부호). 문헌의 활동 중심을 대략 옮긴 것이다.
TELE_TEMPLATES = {
    "nao": [(65, 330, -1), (40, 330, +1), (45, 0, +1)],                       # 아이슬란드 저기압 / 아조레스 고기압
    "pna": [(20, 200, +1), (45, 195, -1), (55, 245, +1), (30, 275, -1)],      # Wallace & Gutzler (1981)
    "wp": [(60, 155, -1), (30, 155, +1)],
    "eu": [(55, 20, -1), (55, 75, +1), (40, 145, -1)],
    "scand": [(62, 30, +1), (45, 350, -1), (45, 110, -1)],
}
TELE_LABEL = {"ao": "북극진동(AO)", "nao": "북대서양진동(NAO)", "pna": "태평양-북미(PNA)", "wp": "서태평양(WP)",
              "eu": "유라시아(EU)", "scand": "스칸디나비아(SCAND)"}
TELE_NMODES = 10            # 회전할 EOF 개수
TELE_MONTHS = (11, 12, 1, 2, 3)

# ---------------------------------------------------------------- SSW 사례 판정
SSW_CASE_LOOKBACK = 75      # 분석 끝 날짜에서 이만큼 앞까지 돌연승온을 찾는다
MINOR_DT_7D = 20.0          # 부 승온: 극관(60~90°N) 10 hPa 기온이 7일 안에 20 K 이상 오름
HEATFLUX_LAT = (45.0, 75.0)
ALEUTIAN = (40, 60, 160, 220)  # 알류샨 저기압 (해면기압 편차)

# ---------------------------------------------------------------- 서술 규칙 (객관 분석 원칙)
SIGMA_STRONG = 1.5          # |σ| ≥ 1.5 → "뚜렷"
SIGMA_WEAK = 0.5            # |σ| < 0.5 → "평년 수준"
