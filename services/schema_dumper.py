"""
PostgreSQL 스키마 덤프 서비스.

pg_dump 바이너리에 의존하지 않고, psycopg2 쿼리로
스키마 구조(DDL)를 SQL 텍스트로 추출한다.
옵션에 따라 데이터(INSERT)도 포함할 수 있다.

pg_dump 대신 직접 구현한 이유:
    - 납품 현장에 pg_dump 바이너리가 설치되어 있지 않을 수 있음
    - 단일 .exe 배포 요건상 외부 바이너리 의존을 최소화해야 함
    - psycopg2만으로 DDL 재구성이 가능

덤프 대상 객체 (추출 순서):
    1. Extensions     : CREATE EXTENSION IF NOT EXISTS (plpgsql 제외)
    2. ENUM Types     : CREATE TYPE ... AS ENUM
    3. Sequences      : CREATE SEQUENCE IF NOT EXISTS
    4. Tables         : CREATE TABLE IF NOT EXISTS (컬럼, PK, UNIQUE, CHECK 포함)
    5. Foreign Keys   : ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY
    6. Indexes        : CREATE INDEX (PK/UNIQUE 제약조건 인덱스 제외)
    7. Views          : CREATE OR REPLACE VIEW
    8. Data (선택)    : INSERT INTO ... VALUES (배치 단위 페치)

덤프 모드:
    - 전체 DB 덤프 (dump_database)  : 모든 사용자 스키마를 순회하며 덤프
    - 선택 덤프 (dump)              : 지정 스키마의 특정 테이블만 덤프

사용처:
    - MainApplication._do_schema_dump() : 백그라운드 스레드에서 호출
"""

import datetime
from typing import Callable, List, Optional

import psycopg2.extensions

from config import SCHEMA_DUMP_BATCH_SIZE


# 로그 콜백 타입 alias
LogCallback = Callable[[str, str], None]


class SchemaDumper:
    """
    psycopg2 쿼리 기반 스키마 덤프를 수행한다.

    pg_catalog / information_schema 시스템 카탈로그를 조회하여
    DDL(Data Definition Language)을 SQL 텍스트로 재구성한다.

    내부 상태:
        _conn : 활성 psycopg2 커넥션 (autocommit=True 상태 권장)
    """

    def __init__(self, conn: psycopg2.extensions.connection):
        """
        SchemaDumper를 초기화한다.

        @param conn  활성 psycopg2 커넥션
        """
        self._conn = conn

    # ==================================================================
    # 전체 DB 덤프
    # ==================================================================

    def dump_database(
        self,
        include_data: bool               = False,
        log:          Optional[LogCallback] = None,
    ) -> str:
        """
        DB 전체를 덤프한다.

        시스템 스키마(pg_*, information_schema)를 제외한 모든 사용자 스키마를 대상으로 한다.
        public 스키마가 먼저 출력되도록 정렬한다.

        @param include_data  데이터(INSERT) 포함 여부
        @param log           로그 콜백 (tag, message)
        @returns             전체 DB 덤프 SQL 문자열

        @example
            dumper = SchemaDumper(conn)
            sql    = dumper.dump_database(include_data=True, log=my_log)
            with open("full_dump.sql", "w") as f:
                f.write(sql)
        """
        if log is None:
            log = lambda tag, msg: None

        schemas = self._get_user_schemas()
        log("INFO", f"대상 스키마 {len(schemas)}개: {', '.join(schemas)}")

        lines = []
        lines.append(f"-- PostgreSQL Full Database Dump")
        lines.append(f"-- Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"-- Schemas: {', '.join(schemas)}")
        lines.append("")

        # Extensions는 DB 레벨이므로 한 번만 출력
        lines.extend(self._dump_extensions(log))

        total_tables = 0
        for schema in schemas:
            schema_sql = self.dump(
                tables=None,
                include_data=include_data,
                schema=schema,
                log=log,
                _skip_header=True,
                _skip_extensions=True,
            )
            if schema_sql.strip():
                lines.append(f"-- ###########################################################")
                lines.append(f"-- SCHEMA: {schema}")
                lines.append(f"-- ###########################################################")
                lines.append("")
                # public 스키마는 기본 존재하므로 CREATE SCHEMA 생략
                if schema != "public":
                    lines.append(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
                    lines.append("")
                lines.append(schema_sql)
                lines.append("")
                total_tables += len(self._get_all_tables(schema))

        log("OK", f"전체 DB 덤프 완료 (스키마 {len(schemas)}개, 테이블 {total_tables}개)")
        return "\n".join(lines)

    def _get_user_schemas(self) -> List[str]:
        """
        시스템 스키마를 제외한 사용자 스키마 목록을 조회한다.

        public 스키마가 리스트 최상단에 오도록 정렬한다.
        (nspname = 'public' DESC -> True(1)가 먼저)

        @returns  스키마명 리스트 (public 우선, 나머지 알파벳순)
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT nspname
                FROM   pg_namespace
                WHERE  nspname NOT LIKE 'pg_%%'
                AND    nspname != 'information_schema'
                ORDER  BY nspname = 'public' DESC, nspname
            """)
            return [row[0] for row in cur.fetchall()]

    # ==================================================================
    # 선택 덤프 (단일 스키마)
    # ==================================================================

    def dump(
        self,
        tables:       Optional[List[str]] = None,
        include_data: bool                = False,
        schema:       str                 = "public",
        log:          Optional[LogCallback] = None,
        _skip_header:     bool = False,
        _skip_extensions: bool = False,
    ) -> str:
        """
        지정 스키마의 덤프를 수행하여 SQL 텍스트를 반환한다.

        tables가 None이면 스키마 내 전체 테이블을, 리스트가 주어지면 해당 테이블만 덤프한다.

        @param tables         덤프 대상 테이블명 리스트 (None이면 전체)
        @param include_data   데이터(INSERT) 포함 여부
        @param schema         대상 스키마명 (기본값: "public")
        @param log            로그 콜백 (tag, message)
        @param _skip_header     내부용: 헤더 주석 생략 여부 (dump_database에서 호출 시 True)
        @param _skip_extensions 내부용: Extensions 섹션 생략 여부 (dump_database에서 호출 시 True)
        @returns              스키마 DDL SQL 문자열

        @example
            dumper = SchemaDumper(conn)
            sql    = dumper.dump(tables=["users", "orders"], schema="public")
        """
        if log is None:
            log = lambda tag, msg: None

        lines = []

        # 헤더 주석
        if not _skip_header:
            lines.append(f"-- PostgreSQL Schema Dump")
            lines.append(f"-- Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"-- Schema: {schema}")
            lines.append("")

        # 대상 테이블 결정
        target_tables = tables
        if target_tables is None:
            target_tables = self._get_all_tables(schema)

        log("INFO", f"[{schema}] 대상 테이블 {len(target_tables)}개 확인")

        # 각 DDL 섹션 추출
        if not _skip_extensions:
            lines.extend(self._dump_extensions(log))
        lines.extend(self._dump_enums(schema, log))
        lines.extend(self._dump_sequences(schema, target_tables, log))

        for table_name in target_tables:
            log("INFO", f"테이블 덤프 중: {schema}.{table_name}")
            lines.extend(self._dump_table(schema, table_name))
            lines.append("")

        lines.extend(self._dump_foreign_keys(schema, target_tables, log))
        lines.extend(self._dump_indexes(schema, target_tables, log))
        lines.extend(self._dump_views(schema, log))

        # 데이터 덤프 (선택)
        if include_data:
            lines.append("")
            lines.append("-- ===========================================")
            lines.append("-- DATA")
            lines.append("-- ===========================================")
            lines.append("")
            for table_name in target_tables:
                log("INFO", f"데이터 덤프 중: {schema}.{table_name}")
                lines.extend(self._dump_data(schema, table_name, log))

        if not _skip_header:
            log("OK", f"스키마 덤프 완료 (테이블 {len(target_tables)}개)")
        return "\n".join(lines)

    # ==================================================================
    # Private: 테이블 목록 조회
    # ==================================================================

    def _get_all_tables(self, schema: str) -> List[str]:
        """
        스키마 내 모든 테이블명을 조회한다.

        @param schema  대상 스키마명
        @returns       테이블명 리스트 (알파벳순)
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT tablename
                FROM   pg_tables
                WHERE  schemaname = %s
                ORDER  BY tablename
            """, (schema,))
            return [row[0] for row in cur.fetchall()]

    # ==================================================================
    # Private: Extensions
    # ==================================================================

    def _dump_extensions(self, log: LogCallback) -> List[str]:
        """
        설치된 확장 목록을 CREATE EXTENSION 구문으로 변환한다.

        plpgsql은 PostgreSQL 기본 내장 확장이므로 제외한다.

        @param log  로그 콜백
        @returns    SQL 라인 리스트 (확장이 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT extname
                FROM   pg_extension
                WHERE  extname != 'plpgsql'
                ORDER  BY extname
            """)
            rows = cur.fetchall()

        if rows:
            lines.append("-- ===========================================")
            lines.append("-- EXTENSIONS")
            lines.append("-- ===========================================")
            lines.append("")
            for (extname,) in rows:
                lines.append(f"CREATE EXTENSION IF NOT EXISTS \"{extname}\";")
                log("INFO", f"확장: {extname}")
            lines.append("")

        return lines

    # ==================================================================
    # Private: ENUM Types
    # ==================================================================

    def _dump_enums(self, schema: str, log: LogCallback) -> List[str]:
        """
        스키마 내 ENUM 타입 정의를 CREATE TYPE 구문으로 추출한다.

        pg_type + pg_enum을 조인하여 enum 라벨을 정렬 순서대로 수집한다.

        @param schema  대상 스키마명
        @param log     로그 콜백
        @returns       SQL 라인 리스트 (ENUM이 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT t.typname,
                       array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
                FROM   pg_type t
                JOIN   pg_enum e      ON e.enumtypid = t.oid
                JOIN   pg_namespace n ON n.oid = t.typnamespace
                WHERE  n.nspname = %s
                GROUP  BY t.typname
                ORDER  BY t.typname
            """, (schema,))
            rows = cur.fetchall()

        if rows:
            lines.append("-- ===========================================")
            lines.append("-- ENUM TYPES")
            lines.append("-- ===========================================")
            lines.append("")
            for typname, labels in rows:
                label_str = ", ".join(f"'{lbl}'" for lbl in labels)
                lines.append(f"CREATE TYPE \"{schema}\".\"{typname}\" AS ENUM ({label_str});")
                log("INFO", f"ENUM 타입: {typname}")
            lines.append("")

        return lines

    # ==================================================================
    # Private: Sequences
    # ==================================================================

    def _dump_sequences(
        self,
        schema: str,
        tables: List[str],
        log:    LogCallback,
    ) -> List[str]:
        """
        스키마 내 시퀀스 정의를 CREATE SEQUENCE 구문으로 추출한다.

        pg_class + pg_sequence를 조인하여 시퀀스 설정값을 수집한다.

        @param schema  대상 스키마명
        @param tables  덤프 대상 테이블 리스트 (현재 필터링 미사용, 향후 확장 대비)
        @param log     로그 콜백
        @returns       SQL 라인 리스트 (시퀀스가 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT s.relname                            AS seq_name,
                       pg_sequence.seqstart                 AS start_val,
                       pg_sequence.seqincrement             AS inc_val,
                       pg_sequence.seqmin                   AS min_val,
                       pg_sequence.seqmax                   AS max_val,
                       pg_sequence.seqcycle                 AS is_cycle
                FROM   pg_class s
                JOIN   pg_namespace n    ON n.oid = s.relnamespace
                JOIN   pg_sequence       ON pg_sequence.seqrelid = s.oid
                WHERE  s.relkind = 'S'
                AND    n.nspname = %s
                ORDER  BY s.relname
            """, (schema,))
            rows = cur.fetchall()

        if rows:
            lines.append("-- ===========================================")
            lines.append("-- SEQUENCES")
            lines.append("-- ===========================================")
            lines.append("")
            for seq_name, start_val, inc_val, min_val, max_val, is_cycle in rows:
                cycle_str = "CYCLE" if is_cycle else "NO CYCLE"
                lines.append(
                    f"CREATE SEQUENCE IF NOT EXISTS \"{schema}\".\"{seq_name}\" "
                    f"START {start_val} INCREMENT {inc_val} "
                    f"MINVALUE {min_val} MAXVALUE {max_val} {cycle_str};"
                )
                log("INFO", f"시퀀스: {seq_name}")
            lines.append("")

        return lines

    # ==================================================================
    # Private: Tables (CREATE TABLE)
    # ==================================================================

    def _dump_table(self, schema: str, table_name: str) -> List[str]:
        """
        단일 테이블의 CREATE TABLE 구문을 생성한다.

        포함 항목:
            - 컬럼 정의 (이름, 타입, DEFAULT, NOT NULL)
            - PRIMARY KEY 제약조건
            - UNIQUE 제약조건
            - CHECK 제약조건

        FOREIGN KEY는 모든 테이블 생성 후 ALTER TABLE로 별도 추가한다.
        (테이블 간 순환 참조 문제 방지)

        @param schema      대상 스키마명
        @param table_name  테이블명
        @returns           SQL 라인 리스트
        """
        lines = []
        lines.append(f"-- Table: {schema}.{table_name}")
        lines.append(f"CREATE TABLE IF NOT EXISTS \"{schema}\".\"{table_name}\" (")

        columns     = self._get_columns(schema, table_name)
        primary_key = self._get_primary_key(schema, table_name)
        uniques     = self._get_unique_constraints(schema, table_name)
        checks      = self._get_check_constraints(schema, table_name)

        # 컬럼 정의 + 제약조건을 콤마로 연결
        col_lines = []
        for col in columns:
            col_def = self._format_column(col)
            col_lines.append(f"    {col_def}")

        if primary_key:
            pk_cols = ", ".join(f'"{c}"' for c in primary_key["columns"])
            col_lines.append(f'    CONSTRAINT "{primary_key["name"]}" PRIMARY KEY ({pk_cols})')

        for uq in uniques:
            uq_cols = ", ".join(f'"{c}"' for c in uq["columns"])
            col_lines.append(f'    CONSTRAINT "{uq["name"]}" UNIQUE ({uq_cols})')

        for ck in checks:
            col_lines.append(f'    CONSTRAINT "{ck["name"]}" CHECK ({ck["definition"]})')

        lines.append(",\n".join(col_lines))
        lines.append(");")

        return lines

    def _get_columns(self, schema: str, table_name: str) -> List[dict]:
        """
        테이블의 컬럼 정의를 조회한다.

        pg_attribute + pg_class + pg_namespace + pg_attrdef를 조인하여
        컬럼명, 타입, NOT NULL, DEFAULT 값을 추출한다.
        시스템 컬럼(attnum <= 0)과 삭제된 컬럼(attisdropped)은 제외한다.

        @param schema      대상 스키마명
        @param table_name  테이블명
        @returns  [{"name": str, "type": str, "not_null": bool, "default": str|None}, ...]
                  attnum 순서 (컬럼 정의 순서) 보장
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT a.attname                                          AS col_name,
                       pg_catalog.format_type(a.atttypid, a.atttypmod)    AS col_type,
                       a.attnotnull                                       AS not_null,
                       pg_get_expr(d.adbin, d.adrelid)                    AS default_val
                FROM   pg_attribute a
                JOIN   pg_class c     ON c.oid = a.attrelid
                JOIN   pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE  n.nspname  = %s
                AND    c.relname  = %s
                AND    a.attnum   > 0
                AND    NOT a.attisdropped
                ORDER  BY a.attnum
            """, (schema, table_name))
            return [
                {
                    "name":     row[0],
                    "type":     row[1],
                    "not_null": row[2],
                    "default":  row[3],
                }
                for row in cur.fetchall()
            ]

    def _format_column(self, col: dict) -> str:
        """
        컬럼 딕셔너리를 SQL 컬럼 정의 문자열로 변환한다.

        출력 형식: "col_name" col_type [DEFAULT expr] [NOT NULL]

        @param col  _get_columns() 반환 딕셔너리 항목
        @returns    SQL 컬럼 정의 문자열 (예: '"id" integer DEFAULT nextval('...') NOT NULL')
        """
        parts = [f'"{col["name"]}"', col["type"]]
        if col["default"] is not None:
            parts.append(f'DEFAULT {col["default"]}')
        if col["not_null"]:
            parts.append("NOT NULL")
        return " ".join(parts)

    # ==================================================================
    # Private: 제약조건 (PK, UNIQUE, CHECK)
    # ==================================================================

    def _get_primary_key(self, schema: str, table_name: str) -> Optional[dict]:
        """
        테이블의 PRIMARY KEY 제약조건을 조회한다.

        pg_constraint (contype='p')를 조회하며,
        복합 PK의 경우 conkey 배열의 순서를 유지한다.

        @param schema      대상 스키마명
        @param table_name  테이블명
        @returns  {"name": str, "columns": List[str]} 또는 None (PK 없음)
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT c.conname,
                       array_agg(a.attname ORDER BY x.n)
                FROM   pg_constraint c
                JOIN   pg_class t     ON t.oid = c.conrelid
                JOIN   pg_namespace s ON s.oid = t.relnamespace
                CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS x(attnum, n)
                JOIN   pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
                WHERE  c.contype  = 'p'
                AND    s.nspname  = %s
                AND    t.relname  = %s
                GROUP  BY c.conname
            """, (schema, table_name))
            row = cur.fetchone()
            if row:
                return {"name": row[0], "columns": row[1]}
            return None

    def _get_unique_constraints(self, schema: str, table_name: str) -> List[dict]:
        """
        테이블의 UNIQUE 제약조건 목록을 조회한다.

        pg_constraint (contype='u')를 조회한다.

        @param schema      대상 스키마명
        @param table_name  테이블명
        @returns  [{"name": str, "columns": List[str]}, ...]
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT c.conname,
                       array_agg(a.attname ORDER BY x.n)
                FROM   pg_constraint c
                JOIN   pg_class t     ON t.oid = c.conrelid
                JOIN   pg_namespace s ON s.oid = t.relnamespace
                CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS x(attnum, n)
                JOIN   pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
                WHERE  c.contype  = 'u'
                AND    s.nspname  = %s
                AND    t.relname  = %s
                GROUP  BY c.conname
                ORDER  BY c.conname
            """, (schema, table_name))
            return [{"name": row[0], "columns": row[1]} for row in cur.fetchall()]

    def _get_check_constraints(self, schema: str, table_name: str) -> List[dict]:
        """
        테이블의 CHECK 제약조건 목록을 조회한다.

        pg_get_constraintdef()가 반환하는 "CHECK (...)" 형식에서
        "CHECK " 접두어와 최외곽 괄호를 제거하여 순수 조건식만 추출한다.

        @param schema      대상 스키마명
        @param table_name  테이블명
        @returns  [{"name": str, "definition": str}, ...]
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT c.conname,
                       pg_get_constraintdef(c.oid)
                FROM   pg_constraint c
                JOIN   pg_class t     ON t.oid = c.conrelid
                JOIN   pg_namespace s ON s.oid = t.relnamespace
                WHERE  c.contype  = 'c'
                AND    s.nspname  = %s
                AND    t.relname  = %s
                ORDER  BY c.conname
            """, (schema, table_name))
            results = []
            for row in cur.fetchall():
                definition = row[1]
                # pg_get_constraintdef 반환값에서 "CHECK " 접두어 제거
                if definition.upper().startswith("CHECK "):
                    definition = definition[6:].strip()
                    # 최외곽 괄호 제거 (CREATE TABLE 내부에서 다시 감싸므로)
                    if definition.startswith("(") and definition.endswith(")"):
                        definition = definition[1:-1]
                results.append({"name": row[0], "definition": definition})
            return results

    # ==================================================================
    # Private: Foreign Keys
    # ==================================================================

    def _dump_foreign_keys(
        self,
        schema: str,
        tables: List[str],
        log:    LogCallback,
    ) -> List[str]:
        """
        FOREIGN KEY 제약조건을 ALTER TABLE 구문으로 추출한다.

        모든 테이블의 CREATE TABLE이 완료된 후 FK를 추가하는 방식으로,
        테이블 간 순환 참조가 있어도 정상 덤프가 가능하다.

        @param schema  대상 스키마명
        @param tables  덤프 대상 테이블명 리스트 (이 리스트에 포함된 테이블의 FK만 추출)
        @param log     로그 콜백
        @returns       SQL 라인 리스트 (FK가 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT c.conname,
                       t.relname                          AS table_name,
                       pg_get_constraintdef(c.oid)        AS def
                FROM   pg_constraint c
                JOIN   pg_class t     ON t.oid = c.conrelid
                JOIN   pg_namespace s ON s.oid = t.relnamespace
                WHERE  c.contype  = 'f'
                AND    s.nspname  = %s
                ORDER  BY t.relname, c.conname
            """, (schema,))
            rows = cur.fetchall()

        # 덤프 대상 테이블의 FK만 필터링
        fk_rows = [r for r in rows if r[1] in tables] if tables else rows

        if fk_rows:
            lines.append("-- ===========================================")
            lines.append("-- FOREIGN KEYS")
            lines.append("-- ===========================================")
            lines.append("")
            for conname, table_name, definition in fk_rows:
                lines.append(
                    f'ALTER TABLE "{schema}"."{table_name}" '
                    f'ADD CONSTRAINT "{conname}" {definition};'
                )
                log("INFO", f"FK: {table_name}.{conname}")
            lines.append("")

        return lines

    # ==================================================================
    # Private: Indexes
    # ==================================================================

    def _dump_indexes(
        self,
        schema: str,
        tables: List[str],
        log:    LogCallback,
    ) -> List[str]:
        """
        인덱스 정의를 추출한다.

        PRIMARY KEY / UNIQUE 제약조건이 자동 생성하는 인덱스는 제외한다.
        (이미 CREATE TABLE에서 제약조건으로 정의되었으므로 중복 방지)

        @param schema  대상 스키마명
        @param tables  덤프 대상 테이블명 리스트
        @param log     로그 콜백
        @returns       SQL 라인 리스트 (인덱스가 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT indexname, indexdef
                FROM   pg_indexes
                WHERE  schemaname = %s
                AND    indexdef NOT LIKE '%%UNIQUE%%'
                AND    indexname NOT IN (
                    SELECT c.conname
                    FROM   pg_constraint c
                    JOIN   pg_class t     ON t.oid = c.conrelid
                    JOIN   pg_namespace s ON s.oid = t.relnamespace
                    WHERE  s.nspname = %s
                    AND    c.contype IN ('p', 'u')
                )
                ORDER  BY tablename, indexname
            """, (schema, schema))
            rows = cur.fetchall()

        # 덤프 대상 테이블의 인덱스만 필터링
        idx_rows = [r for r in rows if self._index_belongs_to(r[1], tables)] if tables else rows

        if idx_rows:
            lines.append("-- ===========================================")
            lines.append("-- INDEXES")
            lines.append("-- ===========================================")
            lines.append("")
            for indexname, indexdef in idx_rows:
                lines.append(f"{indexdef};")
                log("INFO", f"인덱스: {indexname}")
            lines.append("")

        return lines

    def _index_belongs_to(self, indexdef: str, tables: List[str]) -> bool:
        """
        인덱스 정의문에서 대상 테이블 소속 여부를 판별한다.

        CREATE INDEX 구문의 ON 절을 분석하여 테이블명을 매칭한다.
        쌍따옴표로 감싸진 테이블명과 감싸지 않은 테이블명 모두 처리한다.

        @param indexdef  CREATE INDEX 전체 구문 문자열
        @param tables    매칭 대상 테이블명 리스트
        @returns         True이면 대상 테이블 소속
        """
        upper = indexdef.upper()
        for t in tables:
            if f' ON "{t}"' in indexdef or f" ON {t}" in upper:
                return True
        return False

    # ==================================================================
    # Private: Views
    # ==================================================================

    def _dump_views(self, schema: str, log: LogCallback) -> List[str]:
        """
        스키마 내 VIEW 정의를 CREATE OR REPLACE VIEW 구문으로 추출한다.

        pg_views 시스템 뷰에서 definition 컬럼을 조회한다.

        @param schema  대상 스키마명
        @param log     로그 콜백
        @returns       SQL 라인 리스트 (뷰가 없으면 빈 리스트)
        """
        lines = []
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT viewname, definition
                FROM   pg_views
                WHERE  schemaname = %s
                ORDER  BY viewname
            """, (schema,))
            rows = cur.fetchall()

        if rows:
            lines.append("-- ===========================================")
            lines.append("-- VIEWS")
            lines.append("-- ===========================================")
            lines.append("")
            for viewname, definition in rows:
                lines.append(f'CREATE OR REPLACE VIEW "{schema}"."{viewname}" AS')
                lines.append(f"{definition.rstrip(';')};")
                lines.append("")
                log("INFO", f"뷰: {viewname}")

        return lines

    # ==================================================================
    # Private: Data (INSERT)
    # ==================================================================

    def _dump_data(
        self,
        schema:     str,
        table_name: str,
        log:        LogCallback,
    ) -> List[str]:
        """
        테이블 데이터를 INSERT INTO ... VALUES 구문으로 변환한다.

        메모리 효율을 위해 SCHEMA_DUMP_BATCH_SIZE(기본 1000)건 단위로 페치한다.
        각 Python 값은 _format_value()를 통해 SQL 리터럴로 변환된다.

        @param schema      대상 스키마명
        @param table_name  테이블명
        @param log         로그 콜백
        @returns           INSERT 구문 라인 리스트 (데이터 없으면 빈 리스트)
        """
        lines = []

        # 컬럼명 조회
        with self._conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.attname
                FROM   pg_attribute a
                JOIN   pg_class c     ON c.oid = a.attrelid
                JOIN   pg_namespace n ON n.oid = c.relnamespace
                WHERE  n.nspname  = %s
                AND    c.relname  = %s
                AND    a.attnum   > 0
                AND    NOT a.attisdropped
                ORDER  BY a.attnum
            """, (schema, table_name))
            col_names = [row[0] for row in cur.fetchall()]

        if not col_names:
            return lines

        cols_str = ", ".join(f'"{c}"' for c in col_names)

        # 데이터 배치 페치 및 INSERT 생성
        with self._conn.cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{schema}"."{table_name}"'
            )
            row_count = 0
            while True:
                rows = cur.fetchmany(SCHEMA_DUMP_BATCH_SIZE)
                if not rows:
                    break
                for row in rows:
                    vals = ", ".join(self._format_value(v) for v in row)
                    lines.append(
                        f'INSERT INTO "{schema}"."{table_name}" ({cols_str}) '
                        f'VALUES ({vals});'
                    )
                    row_count += 1

            log("OK", f"{table_name}: {row_count}건 데이터 덤프")

        return lines

    def _format_value(self, value) -> str:
        """
        Python 값을 SQL 리터럴 문자열로 변환한다.

        지원 타입:
            - None       -> NULL
            - bool       -> TRUE / FALSE
            - int, float -> 숫자 문자열 그대로
            - bytes      -> E'\\\\xHEX' (PostgreSQL bytea 리터럴)
            - list       -> ARRAY[...] (재귀 처리)
            - 기타       -> '...' (작은따옴표 이스케이프 처리)

        @param value  변환할 Python 값 (psycopg2 fetchall 결과의 각 셀)
        @returns      SQL 리터럴 문자열
        """
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, bytes):
            hex_str = value.hex()
            return f"E'\\\\x{hex_str}'"
        if isinstance(value, list):
            items = ", ".join(self._format_value(v) for v in value)
            return f"ARRAY[{items}]"
        # 문자열: 작은따옴표 이스케이프
        text = str(value).replace("'", "''")
        return f"'{text}'"
