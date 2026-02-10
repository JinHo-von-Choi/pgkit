"""
접속 프리셋 관리 서비스.

JSON 파일 기반으로 접속 정보를 로컬에 저장/불러오기/삭제한다.
비밀번호는 평문 저장이며, 납품 현장 내부망 전용 도구 특성상
별도 암호화는 적용하지 않는다.

저장 형식:
    presets.json - JSON 배열 형태로 ConnectionInfo 딕셔너리를 순서대로 저장.
    [
        {"host": "10.0.0.1", "port": 5432, "user": "admin", "password": "...", "dbname": "mydb", "name": "운영"},
        ...
    ]

파일 위치:
    config.PRESET_FILE (기본: 실행 파일과 동일 디렉토리의 presets.json)

사용처:
    - MainApplication._load_presets()   : 앱 시작 시 프리셋 목록 로드
    - MainApplication._save_preset()    : 현재 입력값을 프리셋으로 저장
    - MainApplication._delete_preset()  : 선택된 프리셋 삭제
    - MainApplication._load_preset()    : 선택된 프리셋의 접속 정보를 UI에 반영
"""

import json
import os
from typing import Dict, List, Optional

from config                 import PRESET_FILE
from models.connection_info import ConnectionInfo


class PresetManager:
    """
    로컬 JSON 파일 기반 접속 프리셋 CRUD를 제공한다.

    내부 상태:
        _file_path : 프리셋 JSON 파일의 절대 경로
    """

    def __init__(self, file_path: str = PRESET_FILE):
        """
        PresetManager를 초기화한다.

        @param file_path  프리셋 JSON 파일 경로 (기본값: config.PRESET_FILE)
        """
        self._file_path = file_path

    def load_all(self) -> List[ConnectionInfo]:
        """
        저장된 모든 프리셋을 로드한다.

        파일이 존재하지 않거나 파싱 실패 시 빈 리스트를 반환한다.

        @returns  ConnectionInfo 리스트 (저장 순서 유지)

        @example
            manager = PresetManager()
            presets = manager.load_all()
            for p in presets:
                print(p.display_name)
        """
        data = self._read_file()
        return [ConnectionInfo.from_dict(item) for item in data]

    def save(self, info: ConnectionInfo) -> None:
        """
        프리셋을 저장한다. 동일한 name이 존재하면 해당 항목을 덮어쓴다.

        name 필드가 비어있으면 ValueError를 발생시킨다.
        파일이 존재하지 않으면 새로 생성한다.

        @param info  저장할 접속 정보 (name 필드 필수)
        @throws      ValueError name이 비어있을 경우

        @example
            info = ConnectionInfo(host="10.0.0.1", name="운영서버", ...)
            manager.save(info)
        """
        if not info.name:
            raise ValueError("프리셋 이름이 지정되지 않았습니다.")

        data    = self._read_file()
        updated = False

        # 동일 name을 가진 기존 프리셋이 있으면 덮어쓰기
        for i, item in enumerate(data):
            if item.get("name") == info.name:
                data[i] = info.to_dict()
                updated = True
                break

        # 새 프리셋이면 리스트 끝에 추가
        if not updated:
            data.append(info.to_dict())

        self._write_file(data)

    def delete(self, name: str) -> bool:
        """
        지정된 이름의 프리셋을 삭제한다.

        @param name  삭제할 프리셋 이름
        @returns     삭제 성공 여부 (True: 삭제됨, False: 해당 이름 없음)

        @example
            deleted = manager.delete("운영서버")
            if deleted:
                print("삭제 완료")
        """
        data     = self._read_file()
        filtered = [item for item in data if item.get("name") != name]

        if len(filtered) == len(data):
            return False

        self._write_file(filtered)
        return True

    def get(self, name: str) -> Optional[ConnectionInfo]:
        """
        이름으로 프리셋을 조회한다.

        @param name  프리셋 이름
        @returns     일치하는 ConnectionInfo 또는 None (미발견 시)

        @example
            info = manager.get("운영서버")
            if info:
                conn = psycopg2.connect(**info.dsn)
        """
        data = self._read_file()
        for item in data:
            if item.get("name") == name:
                return ConnectionInfo.from_dict(item)
        return None

    # ------------------------------------------------------------------
    # Private Methods
    # ------------------------------------------------------------------

    def _read_file(self) -> List[dict]:
        """
        JSON 파일에서 프리셋 목록을 읽는다.

        파일이 존재하지 않거나, JSON 파싱에 실패하거나,
        최상위 구조가 배열이 아닌 경우 빈 리스트를 반환한다.

        @returns  프리셋 딕셔너리 리스트
        """
        if not os.path.exists(self._file_path):
            return []
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def _write_file(self, data: List[dict]) -> None:
        """
        프리셋 목록을 JSON 파일에 기록한다.

        UTF-8 인코딩, ensure_ascii=False (한글 프리셋명 지원),
        indent=2 (사람이 읽기 쉬운 형식)로 저장한다.

        @param data  저장할 프리셋 딕셔너리 리스트
        @throws      IOError 파일 쓰기 실패 시
        """
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
