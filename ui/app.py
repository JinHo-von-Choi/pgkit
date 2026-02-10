"""
메인 애플리케이션 윈도우.

모든 UI 패널을 조합하고, 서비스 레이어를 호출하며,
스레드 기반 비동기 작업을 관리한다.

역할:
    - UI 패널 조합 및 배치 (ConnectionPanel, ActionPanel, StatusPanel, LogPanel)
    - 사용자 이벤트를 서비스 레이어로 라우팅 (Controller 역할)
    - 백그라운드 스레드 생성 및 Queue 기반 로그 폴링

스레드 모델:
    tkinter는 단일 스레드 이벤트 루프이므로, 시간이 걸리는 작업
    (Schema Dump, SQL Execute, Verify)은 daemon 스레드에서 실행한다.
    스레드에서 발생하는 로그는 Queue에 넣고, 메인 스레드에서 50ms 간격으로
    폴링하여 UI에 반영한다.

    특수 큐 메시지:
        ("__DONE__", "")       : 작업 완료 신호 -> 프로그레스 중지, 버튼 활성화
        ("__SUMMARY__", text)  : 요약 텍스트 -> LogPanel.set_summary()
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing  import List, Optional

from config import (
    APP_NAME, APP_VERSION,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    MAX_PREVIEW_LINES,
)
from models.connection_info       import ConnectionInfo
from services.connection_service  import ConnectionService
from services.preset_manager      import PresetManager
from services.schema_dumper       import SchemaDumper
from services.sql_executor        import SqlExecutor, ExecutionResult
from services.verification_service import VerificationService

from ui.connection_panel import ConnectionPanel
from ui.action_panel     import ActionPanel
from ui.status_panel     import StatusPanel
from ui.log_panel        import LogPanel
from ui.dialogs          import (
    TableSelectionDialog,
    FilePreviewDialog,
    ask_preset_name,
)


class MainApplication(tk.Tk):
    """
    애플리케이션 메인 윈도우.

    패널 조합, 이벤트 연결, 스레드 작업 관리를 담당한다.
    tk.Tk를 상속하여 애플리케이션의 최상위 윈도우 역할을 한다.

    내부 상태:
        _conn_service   : DB 접속 관리 서비스 (싱글톤)
        _preset_manager : 프리셋 관리 서비스 (싱글톤)
        _log_queue      : 백그라운드 스레드 -> 메인 스레드 로그 전달 큐
        _is_working     : 현재 백그라운드 작업 진행 여부 플래그
    """

    def __init__(self):
        """
        MainApplication을 초기화한다.

        윈도우 속성 설정, 서비스 인스턴스 생성, UI 빌드, 프리셋 로드,
        로그 큐 폴링 시작을 순서대로 수행한다.
        """
        super().__init__()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.geometry(f"{WINDOW_MIN_WIDTH}x{WINDOW_MIN_HEIGHT}")

        # 서비스 레이어 초기화
        self._conn_service   = ConnectionService()
        self._preset_manager = PresetManager()
        self._log_queue      = queue.Queue()
        self._is_working     = False

        self._build_ui()
        self._load_presets()
        self._poll_log_queue()

    # ==================================================================
    # UI 빌드
    # ==================================================================

    def _build_ui(self):
        """
        UI 패널을 배치한다.

        배치 순서 (상단 -> 하단):
            1. ConnectionPanel : 접속 정보 영역
            2. ActionPanel     : 기능 버튼 영역
            3. StatusPanel     : 프로그레스 바 + 상태 메시지
            4. LogPanel        : 로그 출력 영역 (expand=True로 나머지 공간 차지)
        """
        self._conn_panel = ConnectionPanel(
            self,
            on_test          = self._test_connection,
            on_connect       = self._toggle_connection,
            on_preset_load   = self._load_preset,
            on_preset_save   = self._save_preset,
            on_preset_delete = self._delete_preset,
            on_db_list       = self._fetch_db_list,
        )
        self._conn_panel.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._action_panel = ActionPanel(
            self,
            on_schema_dump = self._schema_dump,
            on_sql_execute = self._sql_execute,
            on_verify      = self._verify_setup,
        )
        self._action_panel.pack(fill=tk.X, padx=8, pady=4)
        self._action_panel.set_enabled(False)    # 초기: DB 미접속 상태이므로 비활성

        self._status_panel = StatusPanel(self)
        self._status_panel.pack(fill=tk.X, padx=8, pady=4)

        self._log_panel = LogPanel(self)
        self._log_panel.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

    # ==================================================================
    # Preset Management
    # ==================================================================

    def _load_presets(self):
        """
        저장된 프리셋 목록을 드롭다운에 반영한다.

        앱 시작 시, 프리셋 저장/삭제 후에 호출된다.
        """
        presets = self._preset_manager.load_all()
        names   = [p.display_name for p in presets]
        self._conn_panel.set_preset_list(names)

    def _load_preset(self, name: str):
        """
        선택된 프리셋의 접속 정보를 UI 필드에 반영한다.

        @param name  선택된 프리셋 이름 (display_name)
        """
        info = self._preset_manager.get(name)
        if info:
            self._conn_panel.set_connection_info(info)
            self._log("INFO", f"프리셋 로드: {name}")

    def _save_preset(self):
        """
        현재 UI 입력값을 프리셋으로 저장한다.

        프리셋 이름을 입력받는 다이얼로그를 표시하고,
        입력된 이름으로 프리셋을 저장한다.
        """
        name = ask_preset_name(self)
        if not name:
            return

        info      = self._conn_panel.get_connection_info()
        info.name = name

        try:
            self._preset_manager.save(info)
            self._load_presets()
            self._log("OK", f"프리셋 저장: {name}")
        except Exception as e:
            self._log("ERROR", f"프리셋 저장 실패: {e}")

    def _delete_preset(self):
        """
        현재 선택된 프리셋을 삭제한다.

        삭제 확인 다이얼로그를 표시하고, 확인 시 삭제를 수행한다.
        """
        info = self._conn_panel.get_connection_info()
        if not info.name:
            messagebox.showwarning("경고", "삭제할 프리셋을 선택하세요.")
            return

        if not messagebox.askyesno("확인", f"프리셋 '{info.name}'을(를) 삭제하시겠습니까?"):
            return

        if self._preset_manager.delete(info.name):
            self._load_presets()
            self._log("OK", f"프리셋 삭제: {info.name}")
        else:
            self._log("ERROR", f"프리셋을 찾을 수 없습니다: {info.name}")

    # ==================================================================
    # Connection
    # ==================================================================

    def _test_connection(self):
        """
        접속 테스트를 수행한다.

        현재 UI 입력값으로 테스트 전용 커넥션을 생성하고 결과를 표시한다.
        활성 커넥션에는 영향을 주지 않는다.
        """
        info = self._conn_panel.get_connection_info()
        self._log("INFO", f"접속 테스트: {info.host}:{info.port}")

        try:
            self._conn_service.test_connection(info)
            self._log("OK", "접속 테스트 성공")
            messagebox.showinfo("성공", "접속 테스트 성공")
        except Exception as e:
            self._log("ERROR", f"접속 테스트 실패: {e}")
            messagebox.showerror("실패", f"접속 테스트 실패:\n{e}")

    def _toggle_connection(self):
        """
        접속/접속 해제를 토글한다.

        접속 중이면 close() 후 UI를 미접속 상태로 전환하고,
        미접속이면 connect() 후 UI를 접속 상태로 전환한다.
        """
        if self._conn_service.is_connected:
            self._conn_service.close()
            self._conn_panel.set_connected_state(False)
            self._action_panel.set_enabled(False)
            self._log("INFO", "접속 해제")
            return

        info = self._conn_panel.get_connection_info()
        self._log("INFO", f"접속 시도: {info.host}:{info.port}/{info.dbname}")

        try:
            self._conn_service.connect(info)
            self._conn_panel.set_connected_state(True)
            self._action_panel.set_enabled(True)
            self._log("OK", f"접속 성공: {info.host}:{info.port}/{info.dbname}")
        except Exception as e:
            self._log("ERROR", f"접속 실패: {e}")
            messagebox.showerror("접속 실패", str(e))

    def _fetch_db_list(self):
        """
        서버의 DB 목록을 조회하여 드롭다운에 반영한다.
        """
        info = self._conn_panel.get_connection_info()
        self._log("INFO", f"DB 목록 조회: {info.host}:{info.port}")

        try:
            databases = self._conn_service.get_databases(info)
            self._conn_panel.set_db_list(databases)
            self._log("OK", f"DB 목록 조회 완료: {len(databases)}개")
        except Exception as e:
            self._log("ERROR", f"DB 목록 조회 실패: {e}")
            messagebox.showerror("오류", f"DB 목록 조회 실패:\n{e}")

    # ==================================================================
    # Schema Dump
    # ==================================================================

    def _schema_dump(self):
        """
        스키마 덤프를 실행한다.

        실행 흐름:
            1. 접속 상태 및 작업 중 여부 확인
            2. Select Tables 옵션 시 테이블 선택 다이얼로그 표시
            3. 저장 경로 선택 다이얼로그 표시
            4. 백그라운드 스레드에서 _do_schema_dump() 실행
        """
        if not self._ensure_connected():
            return
        if self._is_working:
            messagebox.showwarning("경고", "작업이 진행 중입니다.")
            return

        select_mode     = self._action_panel.select_tables
        dump_selections = None    # None = 전체 DB 덤프

        # 테이블 선택 모드
        if select_mode:
            try:
                all_tables = self._conn_service.get_all_tables()
            except Exception as e:
                self._log("ERROR", f"테이블 목록 조회 실패: {e}")
                messagebox.showerror("오류", f"테이블 목록 조회 실패:\n{e}")
                return

            if not all_tables:
                messagebox.showwarning("경고", "현재 DB에 테이블이 없습니다.")
                return

            display_names = [
                f'{t["schema"]}.{t["table"]}' for t in all_tables
            ]
            dialog   = TableSelectionDialog(self, display_names)
            selected = dialog.selected_tables

            if selected is None:
                return
            if not selected:
                messagebox.showwarning("경고", "테이블을 하나 이상 선택하세요.")
                return

            # "schema.table" 형식을 분리하여 {schema: [tables]} 로 그룹핑
            dump_selections = {}
            for name in selected:
                schema, table = name.split(".", 1)
                dump_selections.setdefault(schema, []).append(table)

        # 저장 경로 선택
        save_path = filedialog.asksaveasfilename(
            title="덤프 파일 저장",
            defaultextension=".sql",
            filetypes=[("SQL Files", "*.sql"), ("All Files", "*.*")],
            initialfile="schema_dump.sql",
        )

        if not save_path:
            return

        include_data = self._action_panel.include_data

        self._run_in_thread(
            target=self._do_schema_dump,
            args=(dump_selections, include_data, save_path),
        )

    def _do_schema_dump(
        self,
        selections:   Optional[dict],
        include_data: bool,
        save_path:    str,
    ):
        """
        스레드에서 실행되는 스키마 덤프 작업.

        @param selections  None이면 전체 DB 덤프,
                           {schema: [table, ...]} 이면 선택된 테이블만 덤프
        @param include_data 데이터(INSERT) 포함 여부
        @param save_path    저장할 파일 경로
        """
        try:
            dumper = SchemaDumper(self._conn_service.connection)

            if selections is None:
                # 전체 DB 덤프
                sql = dumper.dump_database(
                    include_data=include_data,
                    log=self._thread_log,
                )
            else:
                # 선택된 테이블만 스키마별로 덤프
                parts = []
                for schema, tables in selections.items():
                    part = dumper.dump(
                        tables=tables,
                        include_data=include_data,
                        schema=schema,
                        log=self._thread_log,
                    )
                    parts.append(part)
                sql = "\n\n".join(parts)

            with open(save_path, "w", encoding="utf-8") as f:
                f.write(sql)

            self._thread_log("OK", f"덤프 파일 저장 완료: {save_path}")

        except Exception as e:
            self._thread_log("ERROR", f"스키마 덤프 실패: {e}")

    # ==================================================================
    # SQL Execute
    # ==================================================================

    def _sql_execute(self):
        """
        SQL 파일을 선택하고 실행한다.

        실행 흐름:
            1. 접속 상태 및 작업 중 여부 확인
            2. 파일 선택 다이얼로그 표시
            3. 단일 파일 선택 시 미리보기 다이얼로그 표시
            4. 실행 확인 다이얼로그 표시
            5. 백그라운드 스레드에서 _do_sql_execute() 실행
        """
        if not self._ensure_connected():
            return
        if self._is_working:
            messagebox.showwarning("경고", "작업이 진행 중입니다.")
            return

        file_paths = filedialog.askopenfilenames(
            title="SQL 파일 선택",
            filetypes=[
                ("SQL Files", "*.sql"),
                ("Text Files", "*.txt"),
                ("All Files", "*.*"),
            ],
        )

        if not file_paths:
            return

        file_paths = list(file_paths)

        # 실행 대상 파일 목록 요약
        preview_msg = f"선택된 파일 {len(file_paths)}개:\n"
        for fp in file_paths:
            preview_msg += f"  - {os.path.basename(fp)}\n"

        # 단일 파일 선택 시 내용 미리보기
        if len(file_paths) == 1:
            preview = SqlExecutor.read_file_preview(file_paths[0], MAX_PREVIEW_LINES)
            FilePreviewDialog(self, file_paths[0], preview)

        if not messagebox.askyesno("실행 확인", f"{preview_msg}\n실행하시겠습니까?"):
            return

        single_tx = self._action_panel.single_transaction

        self._run_in_thread(
            target=self._do_sql_execute,
            args=(file_paths, single_tx),
        )

    def _do_sql_execute(self, file_paths: List[str], single_tx: bool):
        """
        스레드에서 실행되는 SQL 파일 실행 작업.

        @param file_paths  실행할 SQL 파일 경로 리스트
        @param single_tx   단일 트랜잭션 모드 여부
        """
        try:
            executor = SqlExecutor(self._conn_service.connection)
            result   = executor.execute_files(
                file_paths         = file_paths,
                single_transaction = single_tx,
                log                = self._thread_log,
            )
            # 실행 결과 요약을 LogPanel 하단에 표시
            self._log_queue.put(("__SUMMARY__", result.summary))

        except Exception as e:
            self._thread_log("ERROR", f"SQL 실행 실패: {e}")

    # ==================================================================
    # Verification
    # ==================================================================

    def _verify_setup(self):
        """
        세팅 결과를 검증한다.

        접속 상태 확인 후 백그라운드 스레드에서 _do_verify()를 실행한다.
        """
        if not self._ensure_connected():
            return
        if self._is_working:
            messagebox.showwarning("경고", "작업이 진행 중입니다.")
            return

        self._run_in_thread(target=self._do_verify)

    def _do_verify(self):
        """
        스레드에서 실행되는 검증 작업.

        VerificationService를 통해 public 스키마의 세팅 상태를 검증하고,
        결과 요약을 LogPanel 하단에 표시한다.
        """
        try:
            verifier = VerificationService(self._conn_service.connection)
            result   = verifier.verify(log=self._thread_log)

            summary = (
                f"테이블 {result.table_count}개 | "
                f"시퀀스 {result.sequence_count}개 | "
                f"인덱스 {result.index_count}개 | "
                f"뷰 {result.view_count}개"
            )
            self._log_queue.put(("__SUMMARY__", summary))

        except Exception as e:
            self._thread_log("ERROR", f"검증 실패: {e}")

    # ==================================================================
    # Thread Management
    # ==================================================================

    def _run_in_thread(self, target, args=()):
        """
        작업을 백그라운드 daemon 스레드에서 실행한다.

        실행 전: 작업 중 플래그 설정, 버튼 비활성화, 프로그레스 시작
        실행 후: __DONE__ 메시지를 큐에 넣어 _poll_log_queue()가 정리하도록 함

        @param target  스레드에서 실행할 함수
        @param args    함수에 전달할 인자 튜플
        """
        self._is_working = True
        self._action_panel.set_enabled(False)
        self._status_panel.start_progress()
        self._status_panel.set_status("작업 진행 중...")

        def wrapper():
            try:
                target(*args)
            finally:
                self._log_queue.put(("__DONE__", ""))

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()

    def _poll_log_queue(self):
        """
        로그 큐를 폴링하여 UI에 반영한다.

        50ms 간격으로 self.after()를 통해 재귀 호출된다.
        큐에서 메시지를 꺼내어 다음과 같이 처리한다:
            - __DONE__    : 작업 완료 처리 (플래그 해제, 버튼 활성화, 프로그레스 중지)
            - __SUMMARY__ : LogPanel 하단 요약 텍스트 설정
            - 그 외       : LogPanel에 로그 엔트리 추가
        """
        try:
            while True:
                tag, message = self._log_queue.get_nowait()

                if tag == "__DONE__":
                    self._is_working = False
                    self._action_panel.set_enabled(True)
                    self._status_panel.stop_progress()
                    self._status_panel.set_status("Ready")
                    continue

                if tag == "__SUMMARY__":
                    self._log_panel.set_summary(message)
                    continue

                self._log_panel.append(tag, message)

        except queue.Empty:
            pass

        self.after(50, self._poll_log_queue)

    def _thread_log(self, tag: str, message: str):
        """
        백그라운드 스레드에서 안전하게 로그를 추가한다.

        tkinter 위젯은 메인 스레드에서만 조작 가능하므로,
        큐에 메시지를 넣고 _poll_log_queue()가 메인 스레드에서 처리한다.

        @param tag      로그 태그 (INFO, OK, ERROR, WARN)
        @param message  로그 메시지
        """
        self._log_queue.put((tag, message))

    def _log(self, tag: str, message: str):
        """
        메인 스레드에서 직접 로그를 추가한다.

        UI 이벤트 핸들러(접속 테스트, 프리셋 로드 등)에서 사용한다.

        @param tag      로그 태그 (INFO, OK, ERROR, WARN)
        @param message  로그 메시지
        """
        self._log_panel.append(tag, message)

    # ==================================================================
    # Helpers
    # ==================================================================

    def _ensure_connected(self) -> bool:
        """
        DB 접속 상태를 확인한다.

        미접속 시 경고 다이얼로그를 표시하고 False를 반환한다.

        @returns True이면 접속 중, False이면 미접속
        """
        if not self._conn_service.is_connected:
            messagebox.showwarning("경고", "DB에 먼저 접속하세요.")
            return False
        return True

    def destroy(self):
        """
        애플리케이션 종료 시 리소스를 정리한다.

        활성 DB 커넥션을 닫은 후 tkinter 윈도우를 파괴한다.
        """
        self._conn_service.close()
        super().destroy()
