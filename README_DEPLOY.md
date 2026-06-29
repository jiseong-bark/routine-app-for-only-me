# 루틴 체크 앱을 어디서든 쓰는 방법

이 앱은 `DATABASE_URL`이 설정되면 노트북의 `routine_app.db` 대신 클라우드 Postgres DB에 저장합니다.
그 상태로 Streamlit Cloud 같은 곳에 배포하면 노트북이 꺼져 있어도 휴대폰, 태블릿, 노트북에서 같은 주소로 접속해 같은 데이터를 볼 수 있습니다.

## 추천 구조

- 앱 실행: Streamlit Cloud
- 데이터 저장: Supabase Postgres
- 접속 방식: 휴대폰/태블릿/노트북 브라우저에서 배포 주소 접속

## 배포 순서

1. Supabase에서 새 프로젝트를 만들고 Postgres 연결 문자열을 복사합니다.
2. 이 폴더를 GitHub 저장소에 올립니다.
3. Streamlit Cloud에서 GitHub 저장소를 연결하고 `app.py`를 실행 파일로 선택합니다.
4. Streamlit Cloud의 App settings > Secrets에 아래처럼 넣습니다.

```toml
DATABASE_URL = "postgresql://postgres:비밀번호@호스트:5432/postgres"
```

5. 앱을 열면 자동으로 필요한 테이블이 만들어집니다.

## 기존 노트북 데이터 옮기기

기존 `routine_app.db`에 있던 루틴과 체크 기록을 클라우드 DB로 옮기려면, 내 컴퓨터에서 `DATABASE_URL` 환경변수를 설정한 뒤 아래 명령을 실행합니다.

PowerShell 예시:

```powershell
$env:DATABASE_URL = "postgresql://postgres:비밀번호@호스트:5432/postgres"
python migrate_sqlite_to_cloud.py
```

주의: `routine_app.db`와 `.streamlit/secrets.toml`은 개인 데이터/비밀번호가 들어갈 수 있으므로 GitHub에 올리지 않도록 `.gitignore`에 넣어두었습니다.
