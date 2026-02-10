"""
다이얼로그 UI 모음.

테이블 선택 다이얼로그, SQL 파일 미리보기 다이얼로그,
프리셋 이름 입력 다이얼로그를 제공한다.

모든 다이얼로그는 모달(modal) 방식이며, 부모 윈도우를 기준으로
transient 설정되어 부모와 함께 이동/최소화된다.

사용처:
    - TableSelectionDialog : MainApplication._schema_dump()에서 테이블 선택 시
    - FilePreviewDialog    : MainApplication._sql_execute()에서 단일 파일 미리보기 시
    - ask_preset_name      : MainApplication._save_preset()에서 프리셋 이름 입력 시
"""

import tkinter as tk
from tkinter import ttk, simpledialog
from typing  import List, Optional

from config import MAX_PREVIEW_LINES


class TableSelectionDialog(tk.Toplevel):
    """
    덤프 대상 테이블을 체크박스로 선택하는 다이얼로그.

    전체 선택/해제 토글과 확인/취소 버튼을 제공한다.
    모달 다이얼로그로 동작하며, 사용자가 확인/취소할 때까지 부모 윈도우를 차단한다.

    결과 조회:
        dialog = TableSelectionDialog(parent, tables)
        selected = dialog.selected_tables
        # selected: List[str] (확인 시) 또는 None (취소 시)
    """

    def __init__(self, parent, tables: List[str]):
        """
        TableSelectionDialog를 초기화하고 모달로 표시한다.

        생성자 내부에서 wait_window()를 호출하므로,
        다이얼로그가 닫힐 때까지 생성자 호출이 블로킹된다.

        @param parent  부모 윈도우
        @param tables  선택 대상 테이블명 리스트 ("schema.table" 형식)
        """
        super().__init__(parent)
        self.title("테이블 선택")
        self.geometry("400x500")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._tables  = tables
        self._vars    = {}
        self._result: Optional[List[str]] = None

        self._build_ui()
        self.wait_window()

    def _build_ui(self):
        """
        위젯을 배치한다.

        상단: 전체 선택/해제 체크박스 + 테이블 수 표시
        중앙: 스크롤 가능한 체크박스 리스트 (Canvas + Frame)
        하단: 확인/취소 버튼
        """
        # ----- 상단: 전체 선택/해제 -----
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        self._select_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top,
            text="전체 선택/해제",
            variable=self._select_all_var,
            command=self._toggle_all,
        ).pack(side=tk.LEFT)

        ttk.Label(top, text=f"총 {len(self._tables)}개 테이블").pack(side=tk.RIGHT)

        # ----- 중앙: 체크박스 리스트 (스크롤 가능) -----
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8)

        canvas    = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner     = ttk.Frame(canvas)

        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for table in self._tables:
            var = tk.BooleanVar(value=True)
            self._vars[table] = var
            ttk.Checkbutton(inner, text=table, variable=var).pack(
                anchor=tk.W, pady=1
            )

        # ----- 하단: 확인/취소 -----
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill=tk.X)

        ttk.Button(bottom, text="확인", command=self._on_ok).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="취소", command=self._on_cancel).pack(
            side=tk.RIGHT
        )

    # ------------------------------------------------------------------
    # Private: 이벤트 핸들러
    # ------------------------------------------------------------------

    def _toggle_all(self):
        """전체 선택/해제 체크박스 토글 핸들러."""
        val = self._select_all_var.get()
        for var in self._vars.values():
            var.set(val)

    def _on_ok(self):
        """
        확인 버튼 핸들러.

        체크된 테이블명 리스트를 결과에 저장하고 다이얼로그를 닫는다.
        """
        self._result = [
            table for table, var in self._vars.items() if var.get()
        ]
        self.destroy()

    def _on_cancel(self):
        """
        취소 버튼 핸들러.

        결과를 None으로 유지하고 다이얼로그를 닫는다.
        """
        self._result = None
        self.destroy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def selected_tables(self) -> Optional[List[str]]:
        """
        선택된 테이블 목록을 반환한다.

        @returns 선택된 테이블명 리스트 (확인 시) 또는 None (취소 시)
        """
        return self._result


class FilePreviewDialog(tk.Toplevel):
    """
    SQL 파일 내용을 미리보기로 표시하는 다이얼로그.

    읽기 전용 텍스트 위젯에 파일 내용을 표시하며,
    수직/수평 스크롤을 지원한다.
    """

    def __init__(self, parent, file_path: str, content: str):
        """
        FilePreviewDialog를 초기화하고 표시한다.

        @param parent     부모 윈도우
        @param file_path  표시할 파일 경로 (타이틀바에 표시)
        @param content    파일 내용 문자열 (SqlExecutor.read_file_preview 결과)
        """
        super().__init__(parent)
        self.title(f"미리보기: {file_path}")
        self.geometry("700x500")
        self.resizable(True, True)
        self.transient(parent)

        self._build_ui(content)

    def _build_ui(self, content: str):
        """
        위젯을 배치한다.

        상단: 읽기 전용 tk.Text + 수직/수평 스크롤바
        하단: 닫기 버튼
        """
        text_frame = ttk.Frame(self, padding=4)
        text_frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            text_frame,
            wrap=tk.NONE,
            font=("Consolas", 10),
            bg="#1E1E1E",
            fg="#D4D4D4",
            state=tk.NORMAL,
        )

        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        text.insert("1.0", content)
        text.configure(state=tk.DISABLED)

        bottom = ttk.Frame(self, padding=4)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="닫기", command=self.destroy).pack(side=tk.RIGHT)


def ask_preset_name(parent) -> Optional[str]:
    """
    프리셋 이름을 입력받는 간단한 다이얼로그를 표시한다.

    tkinter.simpledialog.askstring을 사용한다.
    입력값의 앞뒤 공백을 제거한 후 반환한다.

    @param parent  부모 윈도우
    @returns       입력된 프리셋 이름 (공백 제거 후) 또는 None (취소 시)

    @example
        name = ask_preset_name(self)
        if name:
            info.name = name
            preset_manager.save(info)
    """
    name = simpledialog.askstring(
        "프리셋 저장",
        "프리셋 이름을 입력하세요:",
        parent=parent,
    )
    if name and name.strip():
        return name.strip()
    return None
