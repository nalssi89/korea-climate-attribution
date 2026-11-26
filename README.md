# korea-climate-attribution

ERA5와 KMA 관측으로 최근 한 달 북반구 전체의 기후인자를 찾고, 한반도를 포함한 동아시아 기온·강수 편차의 원인을 규명한다.
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

## 자료 경로

- 1979~2022: WeatherBench2 ERA5 일평균 (익명, 1.5°와 37층 512x256).
- 2023~최근: Google ARCO-ERA5 원시 netCDF (익명). 필요한 시각·위도 줄만 읽어 1.5°로 상자 평균한다.
- `CDSAPI_KEY`가 있고 `arco.datastores.ecmwf.int`에 닿으면 Google 쪽보다 최근 며칠을 ECMWF ARCO로 보충한다 (실제 접속 검증 전).
- `KMA_API_KEY`가 있고 `apihub.kma.go.kr`에 닿으면 ASOS 일자료를 받아 ERA5와 비교한다 (실제 접속 검증 전).
