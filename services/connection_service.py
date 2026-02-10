"""
PostgreSQL 접속 관리 서비스.

psycopg2를 통한 연결 생성, 테스트, 데이터베이스 목록 조회,
테이블 목록 조회 기능을 제공한다.

단일 활성 커넥션(Single Active Connection) 패턴을 사용하며,
한 시점에 하나의 DB 접속만 유지한다. 새 접속 시 기존 커넥션은 자동으로 닫힌다.

사용처:
    - MainApplication._toggle_connection()  : 접속/해제 토글
    - MainApplication._test_connection()    : 접속 유효성 테스트
    - MainApplication._fetch_db_list()      : DB 드롭다운 목록 갱신
    - SchemaDumper / SqlExecutor / VerificationService : connection 속성을 통해 커넥션 전달
"""

from typing import List, Optional

import psycopg2
import psycopg2.extensions

from models.connection_info import ConnectionInfo


class ConnectionService:
    """
    PostgreSQL 서버 접속을 관리한다.
    단일 활성 커넥션을 유지하며, 필요 시 재접속한다.

    내부 상태:
        _conn : 현재 활성 psycopg2 커넥션 또는 None
    """

    def __init__(self):
        self._conn: Optional[psycopg2.extensions.connection] = None

    @property
    def connection(self) -> Optional[psycopg2.extensions.connection]:
        """
        현재 활성 커넥션을 반환한다.

        SchemaDumper, SqlExecutor 등 서비스 생성 시 이 속성을 통해 커넥션을 주입한다.
        접속 상태가 아닌 경우 None을 반환하므로, 호출 전 is_connected 확인이 권장된다.

        @returns psycopg2 connection 객체 또는 None
        """
        return self._conn

    @property
    def is_connected(self) -> bool:
        """
        커넥션 활성 여부를 반환한다.

        psycopg2 connection.closed 속성을 확인한다.
        closed == 0 이면 열린 상태, 그 외(1 이상)이면 닫힌 상태이다.
        커넥션 객체 자체가 None이거나 속성 접근 시 예외가 발생하면 False를 반환한다.

        @returns True이면 접속 중, False이면 미접속
        """
        if self._conn is None:
            return False
        try:
            return self._conn.closed == 0
        except Exception:
            return False

    def connect(self, info: ConnectionInfo) -> psycopg2.extensions.connection:
        """
        주어진 접속 정보로 PostgreSQL에 연결한다.

        기존 커넥션이 있으면 먼저 close()를 호출하여 정리한 뒤 새 커넥션을 생성한다.
        생성된 커넥션은 autocommit=True로 설정된다. SQL 실행 시 트랜잭션 모드는
        SqlExecutor에서 개별적으로 제어한다.

        @param info  접속 정보 (ConnectionInfo 인스턴스)
        @returns     생성된 psycopg2 connection 객체
        @throws      psycopg2.OperationalError 접속 실패 시 (잘못된 호스트, 포트, 인증 오류 등)

        @example
            service = ConnectionService()
            info    = ConnectionInfo(host="10.0.0.1", user="admin", password="pw", dbname="mydb")
            conn    = service.connect(info)
            # conn.autocommit == True
        """
        self.close()
        self._conn = psycopg2.connect(**info.dsn)
        self._conn.set_session(autocommit=True)
        return self._conn

    def test_connection(self, info: ConnectionInfo) -> bool:
        """
        접속 정보의 유효성을 테스트한다.

        테스트 전용 일회성 커넥션을 생성하고 즉시 닫는다.
        현재 활성 커넥션에는 영향을 주지 않는다.

        @param info  테스트할 접속 정보
        @returns     True (접속 성공 시)
        @throws      psycopg2.OperationalError 접속 실패 시 (호출자가 처리해야 함)

        @example
            try:
                service.test_connection(info)
                print("접속 가능")
            except psycopg2.OperationalError as e:
                print(f"접속 불가: {e}")
        """
        test_conn = psycopg2.connect(**info.dsn)
        test_conn.close()
        return True

    def get_databases(self, info: ConnectionInfo) -> List[str]:
        """
        서버의 데이터베이스 목록을 조회한다.

        시스템 템플릿 DB(template0, template1)를 제외한 사용자 DB만 반환한다.
        조회용 임시 커넥션을 'postgres' DB로 생성하여 pg_database를 조회한 뒤 닫는다.
        현재 활성 커넥션에는 영향을 주지 않는다.

        @param info  접속 정보 (dbname은 내부적으로 'postgres'로 오버라이드됨)
        @returns     데이터베이스명 리스트 (알파벳순 정렬)
        @throws      psycopg2.OperationalError 접속 실패 시

        @example
            databases = service.get_databases(info)
            # -> ["mydb", "postgres", "testdb"]
        """
        # 원본 info를 변경하지 않도록 복사 후 dbname만 오버라이드
        temp_info        = ConnectionInfo.from_dict(info.to_dict())
        temp_info.dbname = "postgres"
        temp_conn        = psycopg2.connect(**temp_info.dsn)
        temp_conn.set_session(autocommit=True)

        try:
            with temp_conn.cursor() as cur:
                cur.execute("""
                    SELECT datname
                    FROM   pg_database
                    WHERE  datistemplate = false
                    ORDER  BY datname
                """)
                return [row[0] for row in cur.fetchall()]
        finally:
            temp_conn.close()

    def get_tables(self, schema: str = "public") -> List[str]:
        """
        현재 접속된 DB의 지정 스키마 내 테이블 목록을 조회한다.

        pg_tables 시스템 카탈로그를 조회하며, 테이블명 알파벳순으로 정렬하여 반환한다.

        @param schema  대상 스키마명 (기본값: "public")
        @returns       테이블명 리스트 (알파벳순 정렬)
        @throws        RuntimeError 미접속 상태에서 호출 시

        @example
            tables = service.get_tables("public")
            # -> ["orders", "products", "users"]
        """
        if not self.is_connected:
            raise RuntimeError("DB에 접속되어 있지 않습니다.")

        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT tablename
                FROM   pg_tables
                WHERE  schemaname = %s
                ORDER  BY tablename
            """, (schema,))
            return [row[0] for row in cur.fetchall()]

    def get_all_tables(self) -> List[dict]:
        """
        현재 접속된 DB의 모든 사용자 스키마에서 테이블 목록을 조회한다.

        시스템 스키마(pg_catalog, pg_toast 등 pg_* 접두어, information_schema)를 제외한다.
        스키마 덤프 시 테이블 선택 다이얼로그에서 전체 목록을 표시할 때 사용한다.

        @returns  [{"schema": str, "table": str}, ...] 형태의 딕셔너리 리스트
                  스키마명, 테이블명 순으로 정렬
        @throws   RuntimeError 미접속 상태에서 호출 시

        @example
            all_tables = service.get_all_tables()
            # -> [{"schema": "public", "table": "users"}, {"schema": "audit", "table": "logs"}]
        """
        if not self.is_connected:
            raise RuntimeError("DB에 접속되어 있지 않습니다.")

        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT schemaname, tablename
                FROM   pg_tables
                WHERE  schemaname NOT LIKE 'pg_%%'
                AND    schemaname != 'information_schema'
                ORDER  BY schemaname, tablename
            """)
            return [
                {"schema": row[0], "table": row[1]}
                for row in cur.fetchall()
            ]

    def get_schemas(self) -> List[str]:
        """
        현재 접속된 DB의 사용자 정의 스키마 목록을 조회한다.

        시스템 스키마(pg_* 접두어, information_schema)를 제외한다.
        pg_namespace 시스템 카탈로그를 조회한다.

        @returns  스키마명 리스트 (알파벳순 정렬)
        @throws   RuntimeError 미접속 상태에서 호출 시

        @example
            schemas = service.get_schemas()
            # -> ["audit", "public"]
        """
        if not self.is_connected:
            raise RuntimeError("DB에 접속되어 있지 않습니다.")

        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT nspname
                FROM   pg_namespace
                WHERE  nspname NOT LIKE 'pg_%%'
                AND    nspname != 'information_schema'
                ORDER  BY nspname
            """)
            return [row[0] for row in cur.fetchall()]

    def close(self):
        """
        활성 커넥션을 닫고 내부 참조를 None으로 초기화한다.

        이미 닫힌 커넥션이거나 None인 경우에도 안전하게 처리한다.
        애플리케이션 종료 시 MainApplication.destroy()에서 호출된다.
        """
        if self._conn is not None:
            try:
                if self._conn.closed == 0:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
