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
EA_LAT = (19.5, 55.5)                       # 동아시아 기온·강수 분석 영역 (20~55°N을 덮는 1.5° 격자). 강수 tp는 이 영역만 저장한다
                                            # (2 m 기온은 강제인자 분석과 모식도를 위해 북반구 전체를 저장하고, 동아시아 지수는 이 영역을 잘라 쓴다)
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
    # 강제인자(눈덮임, 토양수분). 눈 깊이는 물당량 m, 토양수분은 0~7 cm 층 체적함수율(m³/m³)
    "sd": "snow_depth", "swvl1": "volumetric_soil_water_layer_1",
    # 북반구(0~90°N) 강수 mm/일: 모식도 지상 면 변수(7일 평균 강수 편차)용. 동아시아 지수가 쓰는 tp(동아시아만)와 따로 둔다
    "tp_nh": "total_precipitation",
}
PRECIP_FIELDS = ("tp", "tp_nh")             # 일 누적(합)으로 만드는 장 (m → mm/일)
# ARCO 원시 자료(2023~)에만 있는 일별 지상 장: WeatherBench2에 없어 1979년부터 이어 붙이지 못한다.
# 모식도 '지상' 면 변수(지표기온 편차)용이다. 평년은 CDS 월평균(fetch.cds_monthly)으로 만든다(common.skt_clim).
ARCO_ONLY_FIELDS = {"skt": "skin_temperature"}
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

# ---------------------------------------------------------------- 강제인자 (해빙, 해수면온도, 눈덮임, 토양수분, 지면온도)
# 영역 지수: 이름 -> 정의. region = (남, 북, 서, 동), field는 병합된 일별 장(또는 CDS 월평균) 이름.
# surface: "sea"(바다 격자만, 해빙·해수면온도는 육지에서 결측), "land"(육지 비율 0.5 이상 격자만), None(그대로)
# scale: 표시 단위로 바꾸는 배수(비율 → %). 편차이므로 단위는 %p(퍼센트포인트).
SNOW_SWE_FULL = 0.015       # 눈덮임 비율 = min(1, 눈 깊이(물당량 m) / 0.015 m). ECMWF IFS 지면 모형의 눈덮임 비율 식과 같은 꼴(임계 15 kg/m²)
LAND_MIN = 0.5              # 육지 지수에 넣는 격자의 최소 육지 비율
FORCING = {
    "bk_ice": dict(label="바렌츠-카라 해빙", group="해빙", field="ci", region=(65, 85, 30, 90), surface="sea", unit="%p", scale=100.0,
                   ref="Mori et al. (2014, Nat. Geosci.); Kim et al. (2014, Nat. Commun.)"),
    "okhotsk_ice": dict(label="오호츠크해 해빙", group="해빙", field="ci", region=(44, 62, 135, 160), surface="sea", unit="%p", scale=100.0,
                        ref="Honda et al. (1999, J. Climate)"),
    "pdo": dict(label="태평양 십년 진동(PDO)", group="해수면온도", field="sst", region=(20, 70, 110, 260), surface="sea", unit="σ", scale=1.0,
                ref="Mantua et al. (1997, BAMS): 20°N 이북 북태평양 SST 편차(영역 평균 제거) EOF1"),
    "koe_sst": dict(label="쿠로시오-오야시오 확장역 SST", group="해수면온도", field="sst", region=(36, 42, 142, 180), surface="sea", unit="°C",
                    scale=1.0, ref="Kwon et al. (2010, J. Climate) 리뷰의 KOE 영역"),
    "kor_sea_sst": dict(label="한반도 주변 해역 SST", group="해수면온도", field="sst", region=(28, 42, 118, 135), surface="sea", unit="°C",
                        scale=1.0, ref="황해·동중국해·동해 남부(국지 해양 열 공급)"),
    "nino34": dict(label="Niño3.4 SST(참고)", group="해수면온도", field="sst", region=(-5, 5, 190, 240), surface="sea", unit="°C", scale=1.0,
                   ref="기존 회귀 인자와 같은 정의"),
    "eurasia_snow": dict(label="유라시아 눈덮임", group="눈덮임", field="snowc", region=(35, 80, 0, 180), surface="land", unit="%p",
                         scale=100.0, ref="Cohen & Entekhabi (1999, GRL); Cohen & Jones (2011, GRL)"),
    "tibet_snow": dict(label="티베트고원 눈덮임", group="눈덮임", field="snowc", region=(27, 40, 75, 105), surface="land", unit="%p",
                       scale=100.0, ref="Wu & Qian (2003, J. Climate)"),
    "mongolia_sm": dict(label="몽골·시베리아 남부 토양수분", group="토양수분", field="swvl1", region=(40, 55, 90, 120), surface="land",
                        unit="%p(체적)", scale=100.0, ref="Zhang & Zuo (2011, J. Climate); Koster et al. (2004, Science)"),
    "eurasia_t2m": dict(label="유라시아 육지 2 m 기온", group="지면온도", field="t2m", region=(40, 65, 60, 140), surface="land", unit="°C",
                        scale=1.0, ref="시베리아 고기압 영역의 지면 냉각(Gong & Ho 2002, Theor. Appl. Climatol.)"),
    "eurasia_skt": dict(label="유라시아 지면온도(월평균)", group="지면온도", field="skt", region=(40, 65, 60, 140), surface="land", unit="°C",
                        scale=1.0, monthly=True, ref="ERA5 skin temperature 월평균(CDS), 영역은 유라시아 육지 2 m 기온과 같다"),
}
FORCING_TARGETS = {          # 연관성을 볼 대상: 동아시아 기온·강수와 북반구 순환 지수 (indices_daily.csv의 열)
    "korea_t": "한반도 기온", "korea_p": "한반도 강수", "ea_t": "동아시아 기온", "ea_p": "동아시아 강수",
    "ural": "우랄 Z500", "ao": "북극진동(AO)", "pv": "극소용돌이 세기(U10 60°N)", "vt100_anom": "100 hPa 열속",
}
FORCING_LAGS = (0, 1, 2)    # 강제인자가 앞서는 달 수
FORCING_SEASON = (11, 12, 1, 2, 3)   # 묶음 분석에 쓰는 대상 달(늦가을~초봄)
FORCING_REG_LAG = 1         # 회귀 비교에 넣는 강제인자 시차(달). 미리 정해 두고 고르지 않는다(선택 편향 방지)
