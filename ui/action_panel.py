"""
기능 버튼 영역 UI.

Schema Dump, SQL Execute, Verify 버튼과
덤프 옵션(Include Data, Select Tables), 트랜잭션 옵션(Single TX) 토글을 제공한다.

레이아웃:
    좌측: [Schema Dump] [SQL Execute] [Verify]
    우측: Options: [Include Data] [Select Tables] [Single TX]

사용처:
    - MainApplication._build_ui()에서 Connection 패널 아래에 배치
    - 접속 상태에 따라 set_enabled()로 버튼 활성/비활성 전환
"""

import tkinter as tk
from tkinter import ttk
from typing  import Callable


class ActionPanel(ttk.LabelFrame):
    """
    기능 버튼 및 옵션 토글 영역.

    Schema Dump / SQL Execute / Verify 실행 트리거와
    덤프/트랜잭션 옵션을 관리한다.

    콜백 인터페이스:
        on_schema_dump : Schema Dump 버튼 클릭 시
        on_sql_execute : SQL Execute 버튼 클릭 시
        on_verify      : Verify 버튼 클릭 시
    """

    def __init__(
        self,
        parent,
        on_schema_dump: Callable[[], None],
        on_sql_execute: Callable[[], None],
        on_verify:      Callable[[], None],
    ):
        """
        ActionPanel을 초기화한다.

        @param parent          부모 위젯
        @param on_schema_dump  Schema Dump 버튼 클릭 콜백
        @param on_sql_execute  SQL Execute 버튼 클릭 콜백
        @param on_verify       Verify 버튼 클릭 콜백
        """
        super().__init__(parent, text="Actions", padding=8)

        self._on_schema_dump = on_schema_dump
        self._on_sql_execute = on_sql_execute
        self._on_verify      = on_verify

        # 옵션 토글 상태 변수
        self._include_data_var  = tk.BooleanVar(value=False)   # 데이터 포함 덤프 여부
        self._single_tx_var     = tk.BooleanVar(value=False)   # 단일 트랜잭션 모드 여부
        self._select_tables_var = tk.BooleanVar(value=False)   # 테이블 개별 선택 모드 여부

        self._build_ui()

    def _build_ui(self):
        """
        위젯을 배치한다.

        좌측 프레임: 기능 버튼 3개
        우측 프레임: 옵션 토글 체크박스 3개
        """
        # ----- 좌측: 기능 버튼 -----
        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._dump_btn = ttk.Button(
            left, text="Schema Dump", command=self._on_schema_dump, width=14
        )
        self._dump_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._exec_btn = ttk.Button(
            left, text="SQL Execute", command=self._on_sql_execute, width=14
        )
        self._exec_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._verify_btn = ttk.Button(
            left, text="Verify", command=self._on_verify, width=8
        )
        self._verify_btn.pack(side=tk.LEFT, padx=(0, 6))

        # ----- 우측: 옵션 토글 -----
        right = ttk.Frame(self)
        right.pack(side=tk.RIGHT)

        ttk.Label(right, text="Options:").pack(side=tk.LEFT, padx=(0, 4))

        ttk.Checkbutton(
            right,
            text="Include Data",
            variable=self._include_data_var,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Checkbutton(
            right,
            text="Select Tables",
            variable=self._select_tables_var,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Checkbutton(
            right,
            text="Single TX",
            variable=self._single_tx_var,
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Public API: 옵션 상태 조회
    # ------------------------------------------------------------------

    @property
    def include_data(self) -> bool:
        """
        데이터 포함 덤프 옵션 상태를 반환한다.

        True이면 SchemaDumper가 INSERT 문도 생성한다.

        @returns 체크박스 상태
        """
        return self._include_data_var.get()

    @property
    def select_tables(self) -> bool:
        """
        테이블 개별 선택 모드 상태를 반환한다.

        True이면 Schema Dump 시 TableSelectionDialog를 표시한다.

        @returns 체크박스 상태
        """
        return self._select_tables_var.get()

    @property
    def single_transaction(self) -> bool:
        """
        단일 트랜잭션 모드 상태를 반환한다.

        True이면 SqlExecutor가 모든 파일을 하나의 트랜잭션으로 실행한다.

        @returns 체크박스 상태
        """
        return self._single_tx_var.get()

    # ------------------------------------------------------------------
    # Public API: 활성/비활성 제어
    # ------------------------------------------------------------------

    def set_enabled(self, enabled: bool):
        """
        기능 버튼의 활성/비활성 상태를 일괄 변경한다.

        DB 미접속 시 또는 작업 진행 중에 비활성화한다.

        @param enabled  True이면 활성, False이면 비활성
        """
        state = "normal" if enabled else "disabled"
        self._dump_btn.configure(state=state)
        self._exec_btn.configure(state=state)
        self._verify_btn.configure(state=state)
