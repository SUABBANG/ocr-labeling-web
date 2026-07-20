"""테이블 셀 검출 (셀 탭 전용, 로컬 paddle 모델).

검출 로직은 detector.py(paddle) — torch와 DLL 충돌 때문에 **인식 워커
서브프로세스**에서만 구동한다. 여기(매니저)는 그 워커에 셀 검출 요청을 보내
결과만 받는다(워커/프로세스 관리는 recognition 모듈이 담당).
"""
from __future__ import annotations

from ..recognition import _roundtrip


def detect_table_cells(image_path: str) -> list[list[int]]:
    """워커에 이미지 경로를 보내 테이블 셀 bbox [x, y, w, h] 리스트를 받는다."""
    return _roundtrip({"path": image_path, "op": "table"})["cells"]
