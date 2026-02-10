"""
SQL 파일 실행 서비스.

선택된 SQL 파일을 대상 DB에 순차 실행한다.
트랜잭션 모드(전체 단일 트랜잭션 / 파일 단위 커밋)를 지원한다.

트랜잭션 모드:
    - 단일 트랜잭션 (single_transaction=True)
        모든 파일을 하나의 트랜잭션으로 묶어 실행한다.
        중간에 오류 발생 시 전체를 롤백한다.
        DDL + DML을 원자적으로 적용해야 할 때 사용한다.

    - 파일 단위 트랜잭션 (single_transaction=False, 기본)
        각 파일을 독립적인 트랜잭션으로 실행한다.
        특정 파일에서 오류가 발생해도 나머지 파일은 정상 처리된다.
        개별 파일의 성공/실패를 독립적으로 추적할 때 사용한다.

SQL 파싱:
    세미콜론(;) 기준으로 개별 쿼리를 분리하되,
    PostgreSQL 함수/프로시저 내부의 $$ 블록(Dollar-Quoted String)은
    세미콜론 분리 대상에서 제외한다.

인코딩:
    UTF-8 -> CP949 -> Latin-1 순서로 시도하여, 한글 Windows 환경에서
    생성된 SQL 파일도 처리할 수 있다.

사용처:
    - MainApplication._do_sql_execute() : 백그라운드 스레드에서 호출
"""

import os
import time
from typing import Callable, List, Optional

import psycopg2
import psycopg2.extensions


# 로그 콜백 타입 alias
# 첫 번째 인자: 로그 태그 (INFO, OK, ERROR, WARN)
# 두 번째 인자: 로그 메시지 문자열
LogCallback = Callable[[str, str], None]


class ExecutionResult:
    """
    SQL 실행 결과 요약.

    SqlExecutor.execute_files() 실행 후 반환되는 결과 객체로,
    파일별/쿼리별 성공/실패 카운트와 소요 시간을 집계한다.
    MainApplication에서 LogPanel 요약 표시 및 로그 출력에 사용한다.
    """

    def __init__(self):
        self.total_files:   int   = 0      # 실행 대상 파일 총 수
        self.success_files: int   = 0      # 성공적으로 완료된 파일 수
        self.failed_files:  int   = 0      # 오류가 발생한 파일 수
        self.total_queries: int   = 0      # 파싱된 쿼리 총 건수
        self.success_count: int   = 0      # 성공적으로 실행된 쿼리 수
        self.error_count:   int   = 0      # 오류가 발생한 쿼리 수
        self.elapsed_sec:   float = 0.0    # 전체 소요 시간 (초)

    @property
    def summary(self) -> str:
        """
        실행 결과 요약 문자열을 반환한다.

        LogPanel 하단 요약 영역과 로그 출력에 표시된다.

        @returns "파일 N개 (성공 N / 실패 N) | 쿼리 N건 (성공 N / 에러 N) | 소요시간 N.Ns" 형식
        """
        return (
            f"파일 {self.total_files}개 "
            f"(성공 {self.success_files} / 실패 {self.failed_files}) | "
            f"쿼리 {self.total_queries}건 "
            f"(성공 {self.success_count} / 에러 {self.error_count}) | "
            f"소요시간 {self.elapsed_sec:.1f}s"
        )


class SqlExecutor:
    """
    SQL 파일 실행기.

    단일 트랜잭션 모드와 파일 단위 커밋 모드를 지원한다.
    psycopg2 connection 객체를 생성자에서 주입받아 사용한다.

    내부 상태:
        _conn : 활성 psycopg2 커넥션 (ConnectionService.connection에서 전달)
    """

    def __init__(self, conn: psycopg2.extensions.connection):
        """
        SqlExecutor를 초기화한다.

        @param conn  활성 psycopg2 커넥션 (autocommit 상태는 실행 시 내부에서 제어함)
        """
        self._conn = conn

    def execute_files(
        self,
        file_paths:         List[str],
        single_transaction: bool = False,
        log:                Optional[LogCallback] = None,
    ) -> ExecutionResult:
        """
        SQL 파일 목록을 순차 실행한다.

        @param file_paths         실행할 SQL 파일 경로 리스트 (실행 순서 보장)
        @param single_transaction True이면 모든 파일을 단일 트랜잭션으로 처리,
                                  False이면 파일별 독립 트랜잭션으로 처리
        @param log                로그 콜백 함수 (tag: str, message: str) -> None
                                  None이면 로그를 출력하지 않음
        @returns                  ExecutionResult 실행 결과 요약 객체

        @example
            executor = SqlExecutor(conn)
            result   = executor.execute_files(
                file_paths=["schema.sql", "data.sql"],
                single_transaction=True,
                log=lambda tag, msg: print(f"[{tag}] {msg}"),
            )
            print(result.summary)
        """
        if log is None:
            log = lambda tag, msg: None

        result     = ExecutionResult()
        result.total_files = len(file_paths)
        start_time = time.time()

        if single_transaction:
            self._execute_single_transaction(file_paths, result, log)
        else:
            self._execute_per_file(file_paths, result, log)

        result.elapsed_sec = time.time() - start_time
        log("INFO", f"실행 완료: {result.summary}")
        return result

    # ------------------------------------------------------------------
    # 단일 트랜잭션 모드
    # ------------------------------------------------------------------

    def _execute_single_transaction(
        self,
        file_paths: List[str],
        result:     ExecutionResult,
        log:        LogCallback,
    ) -> None:
        """
        모든 파일을 단일 트랜잭션으로 실행한다.

        하나의 쿼리라도 실패하면 전체 트랜잭션을 롤백하고 즉시 반환한다.
        모든 쿼리가 성공해야만 최종 COMMIT이 수행된다.

        autocommit 설정을 일시적으로 변경하며, 완료 후 원래 값으로 복원한다.

        @param file_paths  실행할 SQL 파일 경로 리스트
        @param result      결과를 누적할 ExecutionResult 객체 (in-out)
        @param log         로그 콜백 함수
        """
        prev_autocommit = self._conn.autocommit
        try:
            self._conn.autocommit = False
            log("INFO", "단일 트랜잭션 모드: 시작")

            for file_path in file_paths:
                filename = os.path.basename(file_path)
                log("INFO", f"파일 실행 중: {filename}")

                try:
                    sql     = self._read_file(file_path)
                    queries = self._split_queries(sql)
                    result.total_queries += len(queries)

                    for i, query in enumerate(queries, 1):
                        try:
                            with self._conn.cursor() as cur:
                                cur.execute(query)
                            result.success_count += 1
                        except Exception as e:
                            result.error_count += 1
                            result.failed_files += 1
                            log("ERROR", f"[{filename}] 쿼리 #{i} 오류: {e}")
                            self._conn.rollback()
                            log("ERROR", "트랜잭션 롤백 완료 (전체 취소)")
                            result.failed_files = result.total_files - result.success_files
                            return

                    result.success_files += 1
                    log("OK", f"{filename}: {len(queries)}건 실행 완료")

                except IOError as e:
                    result.failed_files += 1
                    log("ERROR", f"파일 읽기 실패: {filename} - {e}")
                    self._conn.rollback()
                    log("ERROR", "트랜잭션 롤백 완료 (전체 취소)")
                    return

            self._conn.commit()
            log("OK", "트랜잭션 커밋 완료")

        finally:
            # autocommit 설정을 원래 값으로 복원
            self._conn.autocommit = prev_autocommit

    # ------------------------------------------------------------------
    # 파일 단위 트랜잭션 모드
    # ------------------------------------------------------------------

    def _execute_per_file(
        self,
        file_paths: List[str],
        result:     ExecutionResult,
        log:        LogCallback,
    ) -> None:
        """
        파일 단위로 트랜잭션을 실행한다.

        각 파일을 독립적인 트랜잭션으로 처리하며,
        파일 내 쿼리 실패 시 해당 파일의 변경만 롤백하고 다음 파일로 진행한다.

        @param file_paths  실행할 SQL 파일 경로 리스트
        @param result      결과를 누적할 ExecutionResult 객체 (in-out)
        @param log         로그 콜백 함수
        """
        prev_autocommit = self._conn.autocommit

        for file_path in file_paths:
            filename = os.path.basename(file_path)
            log("INFO", f"파일 실행 중: {filename}")

            try:
                sql     = self._read_file(file_path)
                queries = self._split_queries(sql)
                result.total_queries += len(queries)

                self._conn.autocommit = False
                file_error = False

                for i, query in enumerate(queries, 1):
                    try:
                        with self._conn.cursor() as cur:
                            cur.execute(query)
                        result.success_count += 1
                    except Exception as e:
                        result.error_count += 1
                        file_error = True
                        log("ERROR", f"[{filename}] 쿼리 #{i} 오류: {e}")
                        self._conn.rollback()
                        log("WARN", f"{filename}: 롤백 완료")
                        break

                if not file_error:
                    self._conn.commit()
                    result.success_files += 1
                    log("OK", f"{filename}: {len(queries)}건 실행 및 커밋 완료")
                else:
                    result.failed_files += 1

            except IOError as e:
                result.failed_files += 1
                log("ERROR", f"파일 읽기 실패: {filename} - {e}")

        self._conn.autocommit = prev_autocommit

    # ------------------------------------------------------------------
    # 파일 I/O
    # ------------------------------------------------------------------

    def _read_file(self, file_path: str) -> str:
        """
        SQL 파일 내용을 읽는다.

        UTF-8 -> CP949 -> Latin-1 순서로 인코딩을 시도한다.
        한글 Windows 환경에서 생성된 파일(CP949/EUC-KR)도 처리할 수 있다.
        Latin-1은 모든 바이트를 수용하는 폴백 인코딩이다.

        @param file_path  SQL 파일 절대 경로
        @returns          파일 내용 문자열
        @throws           IOError 모든 인코딩 시도 실패 시
        """
        for encoding in ("utf-8", "cp949", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise IOError(f"파일 인코딩을 판별할 수 없습니다: {file_path}")

    # ------------------------------------------------------------------
    # SQL 파싱
    # ------------------------------------------------------------------

    def _split_queries(self, sql: str) -> List[str]:
        """
        SQL 텍스트를 개별 쿼리로 분리한다.

        세미콜론(;) 기준으로 분할하되, 다음을 고려한다:
            - 주석 전용 줄(-- 시작)과 빈 줄은 현재 쿼리 버퍼에 포함하되
              독립 쿼리로 분리하지 않는다.
            - $$ (Dollar-Quoted String) 블록 내부의 세미콜론은 분리 대상에서 제외한다.
              PostgreSQL 함수/프로시저 본문에서 사용되는 패턴이다.
            - 주석만으로 구성된 쿼리는 최종 결과에서 제외한다.

        @param sql  분리 대상 SQL 텍스트 (파일 전체 내용)
        @returns    개별 쿼리 문자열 리스트 (빈 쿼리 제외)

        @example
            queries = executor._split_queries("SELECT 1; SELECT 2;")
            # -> ["SELECT 1;", "SELECT 2;"]

        시간 복잡도: O(n) - SQL 텍스트를 한 번만 순회
        """
        queries   = []
        current   = []
        in_dollar = False

        for line in sql.split("\n"):
            stripped = line.strip()

            # 주석 줄이나 빈 줄은 현재 버퍼에 누적만 한다
            if stripped.startswith("--") or not stripped:
                current.append(line)
                continue

            # $$ 토큰 감지: 홀수 개 등장 시 dollar-quote 블록 진입/이탈 토글
            if "$$" in line:
                count = line.count("$$")
                if count % 2 == 1:
                    in_dollar = not in_dollar

            # dollar-quote 블록 내부에서는 세미콜론을 무시한다
            if in_dollar:
                current.append(line)
                continue

            # 세미콜론으로 끝나는 줄에서 쿼리를 분리한다
            if stripped.endswith(";"):
                current.append(line)
                query = "\n".join(current).strip()
                # 주석만으로 구성된 쿼리는 제외
                if query and not all(
                    l.strip().startswith("--") or not l.strip()
                    for l in query.split("\n")
                ):
                    queries.append(query)
                current = []
            else:
                current.append(line)

        # 파일 끝에 세미콜론 없이 남은 쿼리 처리
        if current:
            query = "\n".join(current).strip()
            if query and not all(
                l.strip().startswith("--") or not l.strip()
                for l in query.split("\n")
            ):
                queries.append(query)

        return queries

    # ------------------------------------------------------------------
    # 파일 미리보기
    # ------------------------------------------------------------------

    @staticmethod
    def read_file_preview(file_path: str, max_lines: int = 500) -> str:
        """
        SQL 파일의 미리보기 텍스트를 반환한다.

        지정된 줄 수까지만 읽어 반환하며, 초과 시 생략 안내 메시지를 추가한다.
        _read_file()과 동일한 인코딩 폴백 전략(UTF-8 -> CP949 -> Latin-1)을 사용한다.

        @param file_path   파일 절대 경로
        @param max_lines   최대 줄 수 (기본값: 500, config.MAX_PREVIEW_LINES 참조)
        @returns           미리보기 텍스트 (줄바꿈 포함)

        @example
            preview = SqlExecutor.read_file_preview("schema.sql", max_lines=100)
            print(preview)
        """
        for encoding in ("utf-8", "cp949", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            lines.append(f"\n... (이후 생략, 최대 {max_lines}줄)")
                            break
                        lines.append(line.rstrip("\n"))
                    return "\n".join(lines)
            except UnicodeDecodeError:
                continue
        return "(파일 인코딩을 판별할 수 없습니다)"
