"""
ui 패키지.

tkinter 기반 GUI 컴포넌트를 제공한다.
MainApplication이 최상위 윈도우이며, 각 패널을 조합하여 전체 UI를 구성한다.

구성 요소:
    - MainApplication   : 메인 윈도우 (tk.Tk), 패널 조합 및 이벤트 라우팅
    - ConnectionPanel   : 접속 정보 입력 영역
    - ActionPanel       : 기능 버튼 및 옵션 토글 영역
    - StatusPanel       : 프로그레스 바 및 상태 메시지
    - LogPanel          : 색상 로그 출력 및 내보내기 영역
    - dialogs           : 테이블 선택, 파일 미리보기, 프리셋 이름 입력 다이얼로그

외부 모듈에서는 패키지 레벨 임포트를 사용한다:
    from ui import MainApplication
"""

from ui.app import MainApplication

__all__ = ["MainApplication"]
