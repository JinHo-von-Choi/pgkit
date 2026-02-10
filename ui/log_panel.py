"""
로그 표시 영역 UI.

타임스탬프 + 색상 구분 로그를 실시간 출력하고,
실행 요약을 하단에 표시한다. 로그 내보내기 기능을 제공한다.

로그 형식:
    "YYYY-MM-DD HH:MM:SS [TAG  ] 메시지"
    TAG별 색상: INFO(회색), OK(민트), ERROR(빨강), WARN(주황)

레이아웃:
    상단: 스크롤 가능한 tk.Text (다크 테마, Consolas 10pt)
    하단: [Export Log] [Clear] ---- [요약 텍스트]

사용처:
    - MainApplication._build_ui()에서 최하단 영역에 배치
    - _poll_log_queue()에서 큐 메시지를 수신하여 append() 호출
    - SqlExecutor / VerificationService의 로그 콜백이 간접 호출
"""

import datetime
import tkinter as tk
from tkinter import ttk, filedialog
from typing  import List, Tuple

from config import LOG_COLORS, LOG_TAG_INFO, LOG_TAG_OK, LOG_TAG_ERROR, LOG_TAG_WARNING


class LogPanel(ttk.LabelFrame):
    """
    로그 출력 및 내보내기 영역.

    색상 태그별로 구분된 로그를 스크롤 가능한 텍스트 위젯에 표시한다.
    내부적으로 모든 로그 엔트리를 리스트에 보관하여 Export 시 활용한다.

    내부 상태:
        _log_entries : (timestamp, tag, message) 튜플 리스트
        _summary_var : 하단 요약 텍스트 StringVar
    """

    def __init__(self, parent):
        """
        LogPanel을 초기화한다.

        @param parent  부모 위젯
        """
        super().__init__(parent, text="Log", padding=4)

        self._log_entries: List[Tuple[str, str, str]] = []
        self._summary_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        """
        위젯을 배치한다.

        상단: tk.Text + 수직/수평 스크롤바 (grid 레이아웃)
        하단: Export Log / Clear 버튼 + 요약 라벨
        """
        # ----- 상단: 로그 텍스트 영역 -----
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self._text = tk.Text(
            text_frame,
            wrap=tk.NONE,
            font=("Consolas", 10),
            bg="#1E1E1E",        # 다크 배경
            fg="#D4D4D4",        # 기본 전경색 (INFO 색상과 동일)
            insertbackground="#D4D4D4",
            state=tk.DISABLED,   # 사용자 직접 편집 방지
            height=15,
        )

        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self._text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        # 로그 태그별 색상 태그 등록
        for tag, color in LOG_COLORS.items():
            self._text.tag_configure(tag, foreground=color)

        # ----- 하단: 버튼 + 요약 -----
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, pady=(4, 0))

        ttk.Button(bottom, text="Export Log", command=self._export_log).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(bottom, text="Clear", command=self.clear).pack(
            side=tk.LEFT, padx=(0, 8)
        )

        ttk.Label(bottom, textvariable=self._summary_var, anchor=tk.E).pack(
            side=tk.RIGHT, fill=tk.X, expand=True
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, tag: str, message: str):
        """
        로그 엔트리를 추가한다.

        타임스탬프를 자동 생성하고, 태그에 맞는 색상으로 텍스트를 삽입한다.
        삽입 후 자동으로 최하단으로 스크롤한다.

        @param tag      로그 레벨 태그 (INFO, OK, ERROR, WARN)
        @param message  로그 메시지 문자열
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag_upper = tag.upper()
        log_line  = f"{timestamp} [{tag_upper:<5}] {message}\n"

        # 내부 리스트에 보관 (Export 용)
        self._log_entries.append((timestamp, tag_upper, message))

        # tk.Text에 색상 태그와 함께 삽입
        self._text.configure(state=tk.NORMAL)
        color_tag = tag_upper if tag_upper in LOG_COLORS else LOG_TAG_INFO
        self._text.insert(tk.END, log_line, color_tag)
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)

    def set_summary(self, summary: str):
        """
        하단 요약 텍스트를 설정한다.

        SQL 실행 결과 또는 검증 결과 요약을 표시할 때 사용한다.

        @param summary  요약 문자열
        """
        self._summary_var.set(summary)

    def clear(self):
        """
        로그를 전체 삭제한다.

        내부 엔트리 리스트, 텍스트 위젯, 요약 텍스트를 모두 초기화한다.
        """
        self._log_entries.clear()
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)
        self._summary_var.set("")

    # ------------------------------------------------------------------
    # Private: 로그 내보내기
    # ------------------------------------------------------------------

    def _export_log(self):
        """
        로그를 텍스트 파일로 내보낸다.

        파일 저장 다이얼로그를 표시하고, 선택된 경로에
        타임스탬프 기반 파일명으로 로그를 저장한다.
        내보내기 결과를 로그에 추가한다.
        """
        if not self._log_entries:
            return

        file_path = filedialog.asksaveasfilename(
            title="로그 내보내기",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile=f"pgtool_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )

        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                for timestamp, tag, message in self._log_entries:
                    f.write(f"{timestamp} [{tag:<5}] {message}\n")
            self.append(LOG_TAG_OK, f"로그 내보내기 완료: {file_path}")
        except IOError as e:
            self.append(LOG_TAG_ERROR, f"로그 내보내기 실패: {e}")
