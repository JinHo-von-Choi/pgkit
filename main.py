"""
PostgreSQL DB Setup Tool - Entry Point

납품 기기의 PostgreSQL 데이터베이스 초기 세팅을 위한 경량 데스크톱 유틸리티.
스키마 덤프, SQL 파일 실행, 세팅 검증 기능을 단일 실행 파일로 제공한다.

주요 기능:
    - Schema Dump  : 대상 DB의 DDL(+데이터)을 SQL 파일로 추출
    - SQL Execute  : 선택한 SQL 파일을 대상 DB에 순차 실행
    - Verify       : 세팅 완료 후 테이블/시퀀스/인덱스/뷰 존재 여부 검증

실행 환경:
    - Python 3.9+
    - 의존성: psycopg2-binary (requirements.txt 참조)
    - 빌드  : PyInstaller를 통한 Windows 단일 .exe 배포 (build.bat / build.spec)

Usage:
    개발 환경  : python main.py
    빌드 결과물: dist/PGSetupTool.exe 직접 실행
"""

import sys
import os

# PyInstaller 번들 환경에서도 패키지 임포트가 정상 동작하도록
# 실행 파일 디렉토리를 sys.path 최상단에 삽입한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import MainApplication


def main():
    """
    애플리케이션 메인 루프를 기동한다.

    MainApplication(tk.Tk)을 인스턴스화하고 tkinter 이벤트 루프를 시작한다.
    윈도우가 닫히면 MainApplication.destroy()에서 DB 커넥션 정리 후 종료된다.
    """
    app = MainApplication()
    app.mainloop()


if __name__ == "__main__":
    main()
