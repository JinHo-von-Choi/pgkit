"""
상태 표시줄 UI.

현재 작업 진행률 및 상태 메시지를 프로그레스 바와 함께 표시한다.

레이아웃:
    [프로그레스 바] [상태 메시지 라벨]

프로그레스 모드:
    - indeterminate (기본): 진행 상황을 알 수 없을 때 애니메이션 표시
    - determinate         : 진행률(0~100%)을 수치로 표시 (현재 미사용, 확장 대비)

사용처:
    - MainApplication._build_ui()에서 Action 패널 아래에 배치
    - _run_in_thread() 시작 시 start_progress() + set_status() 호출
    - _poll_log_queue()에서 __DONE__ 수신 시 stop_progress() 호출
"""

import tkinter as tk
from tkinter import ttk


class StatusPanel(ttk.Frame):
    """
    작업 진행 상태 표시 영역.

    프로그레스 바와 상태 메시지 라벨로 구성된다.
    MainApplication에서 작업 시작/종료 시 상태를 갱신한다.
    """

    def __init__(self, parent):
        """
        StatusPanel을 초기화한다.

        @param parent  부모 위젯
        """
        super().__init__(parent, padding=(8, 4))

        self._status_var = tk.StringVar(value="Ready")

        self._build_ui()

    def _build_ui(self):
        """
        위젯을 배치한다.

        좌측: 프로그레스 바 (indeterminate 모드, 폭 200px)
        우측: 상태 메시지 라벨 (확장 가능)
        """
        self._progress = ttk.Progressbar(
            self, mode="indeterminate", length=200
        )
        self._progress.pack(side=tk.LEFT, padx=(0, 8))

        self._status_label = ttk.Label(
            self, textvariable=self._status_var, anchor=tk.W
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, message: str):
        """
        상태 메시지를 설정한다.

        @param message  표시할 상태 메시지 (예: "Ready", "작업 진행 중...")
        """
        self._status_var.set(message)

    def start_progress(self):
        """
        프로그레스 바 애니메이션을 시작한다.

        indeterminate 모드에서 10ms 간격으로 애니메이션을 갱신한다.
        """
        self._progress.start(10)

    def stop_progress(self):
        """
        프로그레스 바를 중지하고 초기 상태로 리셋한다.
        """
        self._progress.stop()
        self._progress["value"] = 0

    def set_determinate(self, value: int, maximum: int):
        """
        프로그레스 바를 확정형(determinate) 모드로 전환하고 값을 설정한다.

        @param value    현재 진행값
        @param maximum  최대값 (진행률 = value / maximum * 100%)
        """
        self._progress.configure(mode="determinate", maximum=maximum)
        self._progress["value"] = value

    def set_indeterminate(self):
        """
        프로그레스 바를 비확정형(indeterminate) 모드로 전환한다.

        진행률을 알 수 없는 작업에서 사용한다.
        """
        self._progress.configure(mode="indeterminate")
