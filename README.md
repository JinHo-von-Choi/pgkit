# PostgreSQL DB Setup Tool

납품 기기의 PostgreSQL 데이터베이스 초기 세팅을 위한 경량 데스크톱 유틸리티.
스키마 덤프, SQL 파일 실행, 세팅 검증 기능을 단일 실행 파일(PGSetupTool.exe)로 제공한다.


## 주요 기능

### Schema Dump
대상 DB의 DDL 및 데이터를 SQL 파일로 추출한다.
pg_dump 바이너리 의존 없이 psycopg2 쿼리 기반으로 동작한다.

- 추출 대상: 시퀀스, 타입(ENUM), 테이블, 인덱스, 제약조건, 뷰, 함수/프로시저, 트리거
- 옵션: 데이터 포함 덤프(INSERT 문 생성), 테이블 개별 선택

### SQL Execute
선택한 SQL 파일(.sql)을 대상 DB에 순차 실행한다.

- 단일/다중 파일 선택 지원
- 단일 트랜잭션(Single TX) 모드 지원
- Dollar-quoted string(`$$`, `$function$` 등) 파싱 지원
- 다중 인코딩 자동 감지: UTF-8 -> CP949 -> Latin-1 순서 폴백

### Verify
세팅 완료 후 테이블, 시퀀스, 인덱스, 뷰의 존재 여부를 검증한다.

- 스키마별 오브젝트 수 집계
- 검증 결과를 텍스트 파일로 내보내기 가능


## 프로젝트 구조

```
pgtool/
├── main.py                     # 엔트리 포인트
├── config.py                   # 전역 상수 및 설정값
├── requirements.txt            # Python 의존성
├── build.bat                   # Windows 빌드 스크립트
├── build.spec                  # PyInstaller 빌드 스펙
│
├── models/
│   ├── __init__.py
│   └── connection_info.py      # DB 접속 정보 데이터 모델 (dataclass)
│
├── services/
│   ├── __init__.py
│   ├── connection_service.py   # DB 커넥션 관리 (접속/해제/테스트)
│   ├── preset_manager.py       # 접속 프리셋 CRUD (JSON 파일 기반)
│   ├── schema_dumper.py        # 스키마 덤프 (DDL + 데이터 추출)
│   ├── sql_executor.py         # SQL 파일 파싱 및 실행
│   └── verification_service.py # DB 오브젝트 검증
│
├── ui/
│   ├── __init__.py
│   ├── app.py                  # 메인 윈도우 (MainApplication)
│   ├── connection_panel.py     # 접속 정보 입력 패널
│   ├── action_panel.py         # 기능 버튼 및 옵션 패널
│   ├── status_panel.py         # 프로그레스 바 + 상태 메시지
│   ├── log_panel.py            # 실시간 로그 출력 영역
│   └── dialogs.py              # 모달 다이얼로그 (테이블 선택, 파일 미리보기, 프리셋 이름 입력)
│
└── dist/
    ├── PGSetupTool.exe         # 빌드 결과물
    └── presets.json             # 런타임 프리셋 저장 파일
```


## 아키텍처

3계층 분리 구조를 따른다.

| 계층 | 디렉토리 | 책임 |
|------|----------|------|
| Model | `models/` | 데이터 구조 정의 (ConnectionInfo dataclass) |
| Service | `services/` | 비즈니스 로직 (DB 접속, 덤프, 실행, 검증) |
| UI | `ui/` | tkinter 기반 GUI 컴포넌트 |

### 스레딩 모델

장시간 실행 작업(덤프, SQL 실행, 검증)은 데몬 스레드에서 실행되며,
`queue.Queue`를 통해 UI 스레드와 메시지를 교환한다.

- UI 스레드: 50ms 주기로 큐를 폴링하여 로그 메시지 수신
- 워커 스레드: 서비스 로직 실행 후 `__DONE__` / `__SUMMARY__` 특수 메시지 전송
- tkinter의 스레드 안전성 제약을 우회하기 위한 구조


## 요구 사항

- Python 3.9 이상
- PostgreSQL 서버 (접속 대상)

### Python 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| psycopg2-binary | >= 2.9.0 | PostgreSQL 드라이버 |
| pyinstaller | >= 6.0.0 | Windows .exe 빌드 (배포 시에만 필요) |


## 설치 및 실행

### 개발 환경

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 의존성 설치
pip install -r requirements.txt

# 실행
python main.py
```

### 빌드 (Windows)

`build.bat`을 실행하면 4단계를 거쳐 `dist/PGSetupTool.exe`를 생성한다.

```batch
build.bat
```

빌드 단계:
1. 의존성 설치 (psycopg2-binary, pyinstaller)
2. 기존 프로세스 및 빌드 결과물 정리
3. PyInstaller 빌드 (build.spec 기반, 단일 .exe)
4. 빌드 캐시 정리 (build/, __pycache__)

빌드 결과물: `dist/PGSetupTool.exe`


## 사용 방법

### 1. DB 접속

1. Host, Port, Database, User, Password를 입력한다.
2. `Test` 버튼으로 접속을 테스트한다.
3. `Connect` 버튼으로 접속한다.

자주 사용하는 접속 정보는 프리셋으로 저장/로드할 수 있다.

### 2. Schema Dump

1. 접속 상태에서 `Schema Dump` 버튼을 클릭한다.
2. 저장할 SQL 파일 경로를 지정한다.
3. 옵션:
   - `Include Data`: 체크 시 테이블 데이터를 INSERT 문으로 포함
   - `Select Tables`: 체크 시 덤프 대상 테이블을 개별 선택

### 3. SQL Execute

1. 접속 상태에서 `SQL Execute` 버튼을 클릭한다.
2. 실행할 SQL 파일을 선택한다 (다중 선택 가능).
3. 단일 파일 선택 시 미리보기 다이얼로그가 표시된다.
4. 옵션:
   - `Single TX`: 체크 시 모든 파일을 하나의 트랜잭션으로 실행

### 4. Verify

1. 접속 상태에서 `Verify` 버튼을 클릭한다.
2. 검증 결과가 로그에 출력된다.
3. 검증 완료 후 결과 파일 저장 여부를 묻는다.


## 설정

`config.py`에서 전역 설정을 관리한다.

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `DEFAULT_HOST` | localhost | 접속 기본 호스트 |
| `DEFAULT_PORT` | 5432 | 접속 기본 포트 |
| `DEFAULT_USER` | postgres | 접속 기본 사용자 |
| `DEFAULT_DB` | postgres | 접속 기본 데이터베이스 |
| `MAX_PREVIEW_LINES` | 500 | SQL 파일 미리보기 최대 줄 수 |
| `SCHEMA_DUMP_BATCH_SIZE` | 1000 | 데이터 덤프 시 배치 페치 크기 |
| `WINDOW_MIN_WIDTH` | 900 | 윈도우 최소 너비 (px) |
| `WINDOW_MIN_HEIGHT` | 650 | 윈도우 최소 높이 (px) |


## 프리셋 파일 형식

접속 프리셋은 `presets.json`에 JSON 배열로 저장된다.
실행 파일과 동일 디렉토리에 위치한다.

```json
[
    {
        "name": "프리셋명",
        "host": "localhost",
        "port": 5432,
        "database": "mydb",
        "user": "postgres",
        "password": "password"
    }
]
```

패스워드는 평문으로 저장된다. 내부 네트워크 전용 도구 특성상 암호화를 적용하지 않았다.


## 작성자

최진호 (jinho.von.choi@nerdvana.kr)


## 라이선스

MIT License
