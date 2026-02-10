"""
세팅 결과 검증 서비스.

스키마 생성 및 데이터 주입 후 테이블 수, 마스터 데이터 건수 등을
자동 확인하는 검증 쿼리를 실행한다.

검증 항목:
    1. 테이블 수       : pg_tables 카탈로그 카운트
    2. 테이블별 행 수  : 각 테이블에 SELECT count(*) 실행
    3. 시퀀스 수       : pg_class relkind='S' 카운트
    4. 인덱스 수       : pg_indexes 카탈로그 카운트
    5. 뷰 수           : pg_views 카탈로그 카운트

검증 결과는 VerificationResult 객체로 반환되며,
MainApplication에서 LogPanel과 StatusPanel에 표시한다.

사용처:
    - MainApplication._do_verify() : 백그라운드 스레드에서 호출
"""

from typing import Callable, Dict, List, Optional

import psycopg2.extensions


# 로그 콜백 타입 alias
# 첫 번째 인자: 로그 태그 (INFO, OK, ERROR, WARN)
# 두 번째 인자: 로그 메시지 문자열
LogCallback = Callable[[str, str], None]


class VerificationResult:
    """
    DB 세팅 검증 결과를 담는 데이터 객체.

    각 검증 항목의 카운트 값과 오류 메시지를 저장한다.
    MainApplication에서 로그 출력 및 요약 표시에 사용한다.

    속성:
        table_count    : 스키마 내 총 테이블 수
        table_rows     : 테이블명 -> 행 수 매핑 (조회 실패 시 -1)
        sequence_count : 시퀀스 수
        index_count    : 인덱스 수
        view_count     : 뷰 수
        errors         : 검증 과정에서 발생한 오류 메시지 리스트
    """

    def __init__(self):
        self.table_count:    int            = 0
        self.table_rows:     Dict[str, int] = {}
        self.sequence_count: int            = 0
        self.index_count:    int            = 0
        self.view_count:     int            = 0
        self.errors:         List[str]      = []


class VerificationService:
    """
    DB 세팅 결과를 검증한다.

    지정된 스키마에 대해 테이블 존재 여부, 레코드 수,
    시퀀스/인덱스/뷰 수를 확인하여 VerificationResult로 반환한다.

    psycopg2 connection 객체를 생성자에서 주입받아 사용한다.

    내부 상태:
        _conn : 활성 psycopg2 커넥션
    """

    def __init__(self, conn: psycopg2.extensions.connection):
        """
        VerificationService를 초기화한다.

        @param conn  활성 psycopg2 커넥션 (autocommit=True 상태 권장)
        """
        self._conn = conn

    def verify(
        self,
        schema: str = "public",
        log:    Optional[LogCallback] = None,
    ) -> VerificationResult:
        """
        대상 스키마의 세팅 상태를 검증한다.

        테이블 수 -> 테이블별 행 수 -> 시퀀스 수 -> 인덱스 수 -> 뷰 수 순서로
        검증을 수행하며, 각 단계의 결과를 로그 콜백으로 실시간 보고한다.
        검증 중 예외 발생 시 errors 리스트에 메시지를 추가하고 로그에 기록한다.

        @param schema  검증 대상 스키마 (기본값: "public")
        @param log     로그 콜백 함수 (tag: str, message: str) -> None
        @returns       VerificationResult 검증 결과 객체

        @example
            verifier = VerificationService(conn)
            result   = verifier.verify(schema="public", log=my_log_callback)
            print(f"테이블 {result.table_count}개, 시퀀스 {result.sequence_count}개")
        """
        if log is None:
            log = lambda tag, msg: None

        result = VerificationResult()
        log("INFO", "세팅 검증 시작")

        try:
            result.table_count = self._count_tables(schema)
            log("INFO", f"테이블 수: {result.table_count}")

            result.table_rows = self._count_rows_per_table(schema, log)

            result.sequence_count = self._count_sequences(schema)
            log("INFO", f"시퀀스 수: {result.sequence_count}")

            result.index_count = self._count_indexes(schema)
            log("INFO", f"인덱스 수: {result.index_count}")

            result.view_count = self._count_views(schema)
            log("INFO", f"뷰 수: {result.view_count}")

            log("OK", "세팅 검증 완료")

        except Exception as e:
            result.errors.append(str(e))
            log("ERROR", f"검증 중 오류: {e}")

        return result

    # ------------------------------------------------------------------
    # Private: 개별 검증 쿼리
    # ------------------------------------------------------------------

    def _count_tables(self, schema: str) -> int:
        """
        스키마 내 테이블 수를 조회한다.

        @param schema  대상 스키마명
        @returns       테이블 수
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT count(*)
                FROM   pg_tables
                WHERE  schemaname = %s
            """, (schema,))
            return cur.fetchone()[0]

    def _count_rows_per_table(
        self,
        schema: str,
        log:    LogCallback,
    ) -> Dict[str, int]:
        """
        스키마 내 모든 테이블에 대해 행 수를 조회한다.

        각 테이블에 SELECT count(*)를 개별 실행한다.
        특정 테이블 조회 실패 시 해당 테이블의 행 수를 -1로 기록하고
        오류를 로그에 출력한 뒤 나머지 테이블 조회를 계속한다.

        @param schema  대상 스키마명
        @param log     로그 콜백 함수
        @returns       {테이블명: 행 수} 딕셔너리 (조회 실패 시 -1)
        """
        rows = {}
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT tablename
                FROM   pg_tables
                WHERE  schemaname = %s
                ORDER  BY tablename
            """, (schema,))
            tables = [row[0] for row in cur.fetchall()]

        for table in tables:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
                    count = cur.fetchone()[0]
                    rows[table] = count
                    log("INFO", f"  {table}: {count}건")
            except Exception as e:
                rows[table] = -1
                log("ERROR", f"  {table}: 조회 실패 - {e}")

        return rows

    def _count_sequences(self, schema: str) -> int:
        """
        스키마 내 시퀀스 수를 조회한다.

        pg_class의 relkind='S' (Sequence)와 pg_namespace를 조인하여 카운트한다.

        @param schema  대상 스키마명
        @returns       시퀀스 수
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT count(*)
                FROM   pg_class c
                JOIN   pg_namespace n ON n.oid = c.relnamespace
                WHERE  c.relkind = 'S'
                AND    n.nspname = %s
            """, (schema,))
            return cur.fetchone()[0]

    def _count_indexes(self, schema: str) -> int:
        """
        스키마 내 인덱스 수를 조회한다.

        pg_indexes 시스템 뷰를 사용한다.
        PRIMARY KEY, UNIQUE 제약조건이 생성하는 인덱스도 포함된다.

        @param schema  대상 스키마명
        @returns       인덱스 수
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT count(*)
                FROM   pg_indexes
                WHERE  schemaname = %s
            """, (schema,))
            return cur.fetchone()[0]

    def _count_views(self, schema: str) -> int:
        """
        스키마 내 뷰 수를 조회한다.

        pg_views 시스템 뷰를 사용한다.

        @param schema  대상 스키마명
        @returns       뷰 수
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT count(*)
                FROM   pg_views
                WHERE  schemaname = %s
            """, (schema,))
            return cur.fetchone()[0]
