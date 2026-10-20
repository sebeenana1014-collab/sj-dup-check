# S저널 중복기사 검사

- `collect.py` — 10분마다 S저널 RSS·기사 목록에서 새 기사를 가져와 `docs/articles.json`에 저장 (최근 45일 보관)
- `docs/index.html` — 국장용 검사 화면. 원고를 붙여넣으면 저장된 기사와 비교해 같은 보도자료를 찾음
- `.github/workflows/collect.yml` — GitHub Actions 예약 실행 (무료)

검사 화면 주소: GitHub Pages (`Settings → Pages`, `main` 브랜치 `/docs` 폴더)
처음 한 번은 Actions 탭에서 "S저널 기사 수집"을 `backfill` 체크 후 수동 실행하면 최근 45일치가 채워짐.
