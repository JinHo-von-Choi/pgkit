"""
services 패키지.

PostgreSQL 접속, 프리셋 관리, 스키마 덤프, SQL 실행, 검증 등
비즈니스 로직을 담당하는 서비스 클래스를 제공한다.

각 서비스는 독립적으로 동작하며, DB 커넥션이 필요한 서비스는
생성자에서 psycopg2 connection 객체를 주입받는다.

외부 모듈에서는 패키지 레벨 임포트를 사용한다:
    from services import ConnectionService, PresetManager
"""

from services.connection_service  import ConnectionService
from services.preset_manager      import PresetManager
from services.schema_dumper       import SchemaDumper
from services.sql_executor        import SqlExecutor
from services.verification_service import VerificationService

__all__ = [
    "ConnectionService",
    "PresetManager",
    "SchemaDumper",
    "SqlExecutor",
    "VerificationService",
]
