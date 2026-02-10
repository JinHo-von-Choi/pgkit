"""
models 패키지.

데이터 전송 객체(Data Transfer Object) 및 도메인 모델을 정의한다.
현재 ConnectionInfo 단일 모델만 포함한다.

외부 모듈에서는 패키지 레벨 임포트를 사용한다:
    from models import ConnectionInfo
"""

from models.connection_info import ConnectionInfo

__all__ = ["ConnectionInfo"]
