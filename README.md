# korea-climate-attribution

ERA5와 KMA 관측으로 최근 기간(반순·주·월·7일·30일) 북반구 전체의 기후인자를 찾고, 한반도를 포함한 동아시아 기온·강수 편차의 원인을 규명한다.
우랄블로킹, 성층권 돌연승온, 엔소의 영향을 중심으로 본다.

구현 계획은 [PLAN.md](PLAN.md)에 있다.

## 필요한 환경변수

| 이름 | 용도 |
|---|---|
| `CDSAPI_KEY` | Copernicus CDS / ECMWF ARCO 인증 |
| `KMA_API_KEY` | 기상청 API 허브 인증 |

키는 저장소에 넣지 않는다.

## 실행

```bash
pip install -r requirements.txt
python -m src.run                    # 받을 수 있는 가장 최근 날짜까지
python -m src.run --end 2026-11-18   # 끝 날짜 지정 (그날까지 30일을 분석)
python -m src.run --skip-fetch       # 받아 둔 자료로 계산과 보고서만 다시
```

`fetch → indices → diagnose → attribute → report` 순서로 돌고, 이미 받은 파일은 건너뛴다.
처음 실행하면 약 15 GB를 `data/`에 받는다.

| 단계 | 코드 | 산출물 |
|---|---|---|
| 1 자료 수집 | `src/fetch/` | `data/` (git 제외), `outputs/fetch_status.json`, `outputs/validation_overlap.csv` |
| 2 지수 계산 | `src/indices/` | `outputs/indices_daily.csv`, `outputs/events_*.csv`, `outputs/oni_monthly.csv` |
| 3 최근 한 달 진단 | `src/diagnose/` | `reports/figures/fig01~05`, `outputs/recent_summary.json` |
| 4 인자별 영향 | `src/attribute/` | `reports/figures/fig06~11`, `outputs/attribution.json` |
| 5 보고서 | `src/report/` | `reports/report_YYYY-MM-DD.html`, `reports/latest.html` |
| 기간 단위 | `src/periods.py`, `src/attribute/periods.py` | `outputs/periods_summary.json` (반순·주·월·최근 7일·30일) |
| SSW 사례 | `src/diagnose/ssw.py` | `outputs/ssw_case.json`, `reports/figures/fig12~13` |
| 6·7 사이트 | `src/export.py`, `site/` | `site/data/*.json`, 대시보드 `site/index.html`, 모식도 `site/schematic/` |

## 자료 경로

- 1979~2022: WeatherBench2 ERA5 일평균 (익명, 1.5°와 37층 512x256).
- 2023~최근: Google ARCO-ERA5 원시 netCDF (익명). 필요한 시각·위도 줄만 읽어 1.5°로 상자 평균한다.
- ECMWF ARCO(`CDSAPI_KEY`): 2026-11-26 실제 접속 확인. 기압면 저장소가 13층(50 hPa까지)이라 10·30 hPa가 없고
  끝 시각도 Google 원시 자료보다 이르다. 그래서 하루 파일 보충은 건너뛰고, 겹치는 날로 교차 검증만 한다.
- KMA ASOS(`KMA_API_KEY`, 없으면 `KMA_AUTHKEY`): 연 단위로 받아 ERA5 한반도 값과 비교한다. 사이트에는 전국 평균 편차만 싣는다.

## 대시보드와 모식도

`python -m src.run --end YYYY-MM-DD` 마지막 단계가 `site/data/`를 갱신한다. 로컬에서 보려면

```bash
python -m http.server -d site 8000
```

`main`에 병합되면 GitHub Pages(https://nalssi89.github.io/korea-climate-attribution/)로 자동 배포된다.
