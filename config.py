"""
PostgreSQL DB Setup Tool - Application Configuration

애플리케이션 전역 상수 및 설정값 정의.
모든 모듈에서 참조하는 단일 설정 소스(Single Source of Truth)로 기능한다.

구성 항목:
    - 애플리케이션 메타 정보 (이름, 버전)
    - PostgreSQL 접속 기본값
    - 프리셋 파일 경로
    - UI 윈도우 크기 제한
    - SQL 미리보기 제한
    - 로그 태그 및 색상 매핑
    - 스키마 덤프 배치 사이즈
"""

import os
import sys


def get_app_dir() -> str:
    """
    실행 파일 기준 디렉토리를 반환한다.

    PyInstaller로 번들된 환경에서는 sys.frozen 어트리뷰트가 True로 설정되며,
    이 경우 sys.executable 경로를 기준으로 한다.
    개발 환경에서는 이 파일(__file__)의 디렉토리를 기준으로 한다.

    @returns 실행 파일 또는 소스 파일이 위치한 디렉토리의 절대 경로

    @example
        # PyInstaller 번들 환경
        # sys.executable = "C:/deploy/PGSetupTool.exe"
        # -> "C:/deploy"

        # 개발 환경
        # __file__ = "C:/dev/pgtool/config.py"
        # -> "C:/dev/pgtool"
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 애플리케이션 메타 정보
# ---------------------------------------------------------------------------
APP_NAME    = "PostgreSQL DB Setup Tool"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# PostgreSQL 접속 기본값
# ConnectionPanel 초기화 시 입력 필드에 표시되는 기본값이다.
# ---------------------------------------------------------------------------
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_USER = "postgres"
DEFAULT_DB   = "postgres"

# ---------------------------------------------------------------------------
# 프리셋 저장 파일 경로
# 실행 파일과 동일 디렉토리에 presets.json으로 저장된다.
# PresetManager에서 읽기/쓰기 대상으로 사용한다.
# ---------------------------------------------------------------------------
PRESET_FILE = os.path.join(get_app_dir(), "presets.json")

# ---------------------------------------------------------------------------
# UI 윈도우 크기 제한
# MainApplication 초기화 시 minsize()에 전달된다.
# ---------------------------------------------------------------------------
WINDOW_MIN_WIDTH  = 900
WINDOW_MIN_HEIGHT = 650

# ---------------------------------------------------------------------------
# SQL 파일 미리보기 최대 줄 수
# SqlExecutor.read_file_preview()와 FilePreviewDialog에서 사용한다.
# ---------------------------------------------------------------------------
MAX_PREVIEW_LINES = 500

# ---------------------------------------------------------------------------
# 로그 태그 상수
# LogPanel에서 색상 구분에 사용하며, 각 서비스의 로그 콜백 호출 시 태그로 전달한다.
# ---------------------------------------------------------------------------
LOG_TAG_INFO    = "INFO"
LOG_TAG_OK      = "OK"
LOG_TAG_ERROR   = "ERROR"
LOG_TAG_WARNING = "WARN"

# ---------------------------------------------------------------------------
# 로그 태그별 색상 매핑 (HEX)
# LogPanel._build_ui()에서 tk.Text 태그 foreground에 적용한다.
# 다크 테마(배경 #1E1E1E) 기준으로 가독성을 확보한 색상이다.
# ---------------------------------------------------------------------------
LOG_COLORS = {
    LOG_TAG_INFO:    "#D4D4D4",   # 연한 회색 - 일반 정보
    LOG_TAG_OK:      "#4EC9B0",   # 민트 그린 - 성공
    LOG_TAG_ERROR:   "#F44747",   # 빨간색   - 오류
    LOG_TAG_WARNING: "#CCA700",   # 주황색   - 경고
}

# ---------------------------------------------------------------------------
# 스키마 덤프 시 데이터 INSERT 문 생성용 배치 사이즈
# SchemaDumper._dump_data()에서 cursor.fetchmany()에 전달한다.
# 메모리 사용량과 쿼리 성능 간 균형을 위해 1000건 단위로 페치한다.
# ---------------------------------------------------------------------------
SCHEMA_DUMP_BATCH_SIZE = 1000
