"""
PostgreSQL 접속 정보 데이터 모델.

하나의 PostgreSQL 서버 접속에 필요한 모든 파라미터를 캡슐화한다.
psycopg2 연결, 프리셋 저장/복원, UI 표시 등 여러 계층에서 공통으로 사용하는
핵심 데이터 구조체이다.

사용처:
    - ConnectionService : connect() / test_connection() 시 DSN 파라미터 제공
    - PresetManager     : JSON 직렬화/역직렬화를 통한 프리셋 영속화
    - ConnectionPanel   : UI 입력 필드 <-> ConnectionInfo 양방향 바인딩
    - SchemaDumper      : 간접 참조 (ConnectionService를 통해 접속 후 connection 전달)
"""

from dataclasses import dataclass, field, asdict
from typing      import Optional


@dataclass
class ConnectionInfo:
    """
    PostgreSQL 서버 접속에 필요한 정보를 캡슐화한다.

    불변 값 객체(Value Object)로 설계되었으며, dataclass의 기본 __eq__을 통해
    필드 값 기반 동등성 비교가 가능하다.

    @param host     서버 IP 주소 또는 도메인명 (예: "192.168.0.100", "localhost")
    @param port     서버 포트 번호 (PostgreSQL 기본값: 5432)
    @param user     접속 사용자명 (예: "postgres", "admin")
    @param password  접속 비밀번호 (평문 저장 - 내부망 전용 도구 특성)
    @param dbname   접속 대상 데이터베이스명 (예: "postgres", "mydb")
    @param name     프리셋 저장 시 사용할 사용자 지정 별칭 (예: "운영서버", "테스트DB")

    @example
        info = ConnectionInfo(
            host="192.168.0.100",
            port=5432,
            user="admin",
            password="secret",
            dbname="production",
            name="운영서버",
        )
        conn = psycopg2.connect(**info.dsn)
    """
    host:     str = "localhost"
    port:     int = 5432
    user:     str = "postgres"
    password: str = ""
    dbname:   str = "postgres"
    name:     str = ""

    @property
    def display_name(self) -> str:
        """
        프리셋 드롭다운에 표시할 이름을 반환한다.

        name 필드가 설정되어 있으면 해당 값을 사용하고,
        비어있으면 "user@host:port/dbname" 형식으로 자동 생성한다.

        @returns 표시용 문자열

        @example
            ConnectionInfo(name="운영").display_name       # -> "운영"
            ConnectionInfo(name="").display_name            # -> "postgres@localhost:5432/postgres"
        """
        if self.name:
            return self.name
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"

    @property
    def dsn(self) -> dict:
        """
        psycopg2.connect()에 키워드 인자로 전달할 파라미터 딕셔너리를 반환한다.

        name 필드는 psycopg2 연결과 무관한 프리셋 관리용 메타데이터이므로 제외한다.

        @returns psycopg2 connect() 호환 딕셔너리
                 {"host": str, "port": int, "user": str, "password": str, "dbname": str}

        @example
            info = ConnectionInfo(host="10.0.0.1", port=5432, user="pg", password="pw", dbname="mydb")
            conn = psycopg2.connect(**info.dsn)
        """
        return {
            "host":     self.host,
            "port":     self.port,
            "user":     self.user,
            "password": self.password,
            "dbname":   self.dbname,
        }

    def to_dict(self) -> dict:
        """
        JSON 직렬화를 위한 딕셔너리를 반환한다.

        dataclasses.asdict()를 사용하여 모든 필드를 포함한다.
        PresetManager._write_file()에서 json.dump() 시 사용한다.

        @returns 전체 필드를 포함한 딕셔너리
                 {"host": str, "port": int, "user": str, "password": str, "dbname": str, "name": str}
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConnectionInfo":
        """
        딕셔너리로부터 ConnectionInfo 인스턴스를 생성한다.

        누락된 키에 대해 기본값을 적용하므로, 불완전한 딕셔너리도 안전하게 처리한다.
        PresetManager._read_file()에서 JSON 파싱 후 사용한다.

        @param data  접속 정보가 담긴 딕셔너리. 키가 누락되면 각 필드의 기본값이 적용된다.
        @returns     ConnectionInfo 인스턴스

        @example
            raw = {"host": "10.0.0.1", "port": 5432, "user": "admin"}
            info = ConnectionInfo.from_dict(raw)
            # info.password == ""  (기본값 적용)
            # info.dbname == "postgres"  (기본값 적용)
        """
        return cls(
            host     = data.get("host", "localhost"),
            port     = int(data.get("port", 5432)),
            user     = data.get("user", "postgres"),
            password = data.get("password", ""),
            dbname   = data.get("dbname", "postgres"),
            name     = data.get("name", ""),
        )
