"""
접속 정보 패널 UI.

프리셋 드롭다운, IP/Port/User/Password/Database 입력 필드,
접속 테스트 버튼, DB 목록 드롭다운을 제공한다.

레이아웃 (2행 구조):
    Row 0: [Preset 드롭다운] [Save] [Delete]
    Row 1: [Host] [Port] [User] [Password] [DB 드롭다운] [List] [Test] [Connect]

사용처:
    - MainApplication._build_ui()에서 상단 영역에 배치
    - ConnectionInfo <-> UI 필드 양방향 바인딩을 담당
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing  import Callable, List, Optional

from config                 import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USER, DEFAULT_DB
from models.connection_info import ConnectionInfo


class ConnectionPanel(ttk.LabelFrame):
    """
    상단 접속 정보 영역.

    프리셋 선택, 접속 파라미터 입력, 접속 테스트, DB 선택을 담당한다.
    각 버튼 클릭 시 생성자에서 전달받은 콜백 함수를 호출한다.

    콜백 인터페이스:
        on_test          : 접속 테스트 실행
        on_connect       : 접속/해제 토글
        on_preset_load   : 프리셋 선택 시 (name: str)
        on_preset_save   : 현재 입력값 프리셋 저장
        on_preset_delete : 선택된 프리셋 삭제
        on_db_list       : DB 목록 조회
    """

    def __init__(
        self,
        parent,
        on_test:          Callable[[], None],
        on_connect:       Callable[[], None],
        on_preset_load:   Callable[[str], None],
        on_preset_save:   Callable[[], None],
        on_preset_delete: Callable[[], None],
        on_db_list:       Callable[[], None],
    ):
        """
        ConnectionPanel을 초기화한다.

        @param parent          부모 위젯
        @param on_test         접속 테스트 버튼 클릭 콜백
        @param on_connect      Connect/Disconnect 버튼 클릭 콜백
        @param on_preset_load  프리셋 드롭다운 선택 콜백 (선택된 프리셋 이름 전달)
        @param on_preset_save  프리셋 Save 버튼 클릭 콜백
        @param on_preset_delete 프리셋 Delete 버튼 클릭 콜백
        @param on_db_list      DB List 버튼 클릭 콜백
        """
        super().__init__(parent, text="Connection", padding=8)

        self._on_test          = on_test
        self._on_connect       = on_connect
        self._on_preset_load   = on_preset_load
        self._on_preset_save   = on_preset_save
        self._on_preset_delete = on_preset_delete
        self._on_db_list       = on_db_list

        # tkinter StringVar: UI 입력 필드와 양방향 바인딩
        self._preset_var = tk.StringVar()
        self._host_var   = tk.StringVar(value=DEFAULT_HOST)
        self._port_var   = tk.StringVar(value=str(DEFAULT_PORT))
        self._user_var   = tk.StringVar(value=DEFAULT_USER)
        self._pass_var   = tk.StringVar()
        self._db_var     = tk.StringVar(value=DEFAULT_DB)

        self._build_ui()

    def _build_ui(self):
        """
        위젯을 배치한다.

        Row 0: 프리셋 드롭다운 + Save/Delete 버튼
        Row 1: Host/Port/User/Password 입력 필드 + DB 드롭다운 + List/Test/Connect 버튼
        """
        # ----- Row 0: 프리셋 영역 -----
        row0 = ttk.Frame(self)
        row0.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(row0, text="Preset:").pack(side=tk.LEFT, padx=(0, 4))
        self._preset_combo = ttk.Combobox(
            row0,
            textvariable=self._preset_var,
            state="readonly",
            width=25,
        )
        self._preset_combo.pack(side=tk.LEFT, padx=(0, 4))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        ttk.Button(row0, text="Save", width=6, command=self._on_preset_save).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(row0, text="Delete", width=6, command=self._on_preset_delete).pack(
            side=tk.LEFT, padx=2
        )

        # ----- Row 1: 접속 파라미터 + 버튼 -----
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X)

        fields = [
            ("Host:",     self._host_var, 18),
            ("Port:",     self._port_var, 6),
            ("User:",     self._user_var, 12),
            ("Password:", self._pass_var, 12),
        ]

        for label_text, var, width in fields:
            ttk.Label(row1, text=label_text).pack(side=tk.LEFT, padx=(8, 2))
            entry = ttk.Entry(row1, textvariable=var, width=width)
            if label_text == "Password:":
                entry.configure(show="*")
            entry.pack(side=tk.LEFT, padx=(0, 2))

        ttk.Label(row1, text="DB:").pack(side=tk.LEFT, padx=(8, 2))
        self._db_combo = ttk.Combobox(
            row1,
            textvariable=self._db_var,
            width=15,
        )
        self._db_combo.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(row1, text="List", width=4, command=self._on_db_list).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(row1, text="Test", width=5, command=self._on_test).pack(
            side=tk.LEFT, padx=2
        )
        self._connect_btn = ttk.Button(
            row1, text="Connect", width=8, command=self._on_connect
        )
        self._connect_btn.pack(side=tk.LEFT, padx=2)

    # ------------------------------------------------------------------
    # Public API: 데이터 입출력
    # ------------------------------------------------------------------

    def get_connection_info(self) -> ConnectionInfo:
        """
        현재 UI에 입력된 접속 정보를 ConnectionInfo 객체로 반환한다.

        각 StringVar에서 값을 추출하여 strip() 처리 후 반환한다.
        Port 필드가 비어있으면 기본값(5432)을 적용한다.

        @returns ConnectionInfo 인스턴스
        """
        return ConnectionInfo(
            host     = self._host_var.get().strip(),
            port     = int(self._port_var.get().strip() or DEFAULT_PORT),
            user     = self._user_var.get().strip(),
            password = self._pass_var.get(),
            dbname   = self._db_var.get().strip(),
            name     = self._preset_var.get().strip(),
        )

    def set_connection_info(self, info: ConnectionInfo):
        """
        ConnectionInfo 객체의 값을 UI 입력 필드에 반영한다.

        프리셋 로드 시 호출된다.

        @param info  반영할 접속 정보
        """
        self._host_var.set(info.host)
        self._port_var.set(str(info.port))
        self._user_var.set(info.user)
        self._pass_var.set(info.password)
        self._db_var.set(info.dbname)

    def set_preset_list(self, names: List[str]):
        """
        프리셋 드롭다운의 선택 항목 목록을 갱신한다.

        @param names  프리셋 이름 리스트
        """
        self._preset_combo["values"] = names

    def set_db_list(self, databases: List[str]):
        """
        DB 드롭다운의 선택 항목 목록을 갱신한다.

        @param databases  데이터베이스명 리스트
        """
        self._db_combo["values"] = databases

    def set_connected_state(self, connected: bool):
        """
        접속 상태에 따라 Connect 버튼 텍스트를 변경한다.

        @param connected  True이면 "Disconnect", False이면 "Connect" 표시
        """
        self._connect_btn.configure(
            text="Disconnect" if connected else "Connect"
        )

    # ------------------------------------------------------------------
    # Private: 이벤트 핸들러
    # ------------------------------------------------------------------

    def _on_preset_selected(self, event=None):
        """
        프리셋 드롭다운 선택(<<ComboboxSelected>>) 이벤트 핸들러.

        선택된 프리셋 이름을 on_preset_load 콜백에 전달한다.
        """
        name = self._preset_var.get()
        if name:
            self._on_preset_load(name)
