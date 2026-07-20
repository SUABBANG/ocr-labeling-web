"""테이블 셀 검출 predictor (paddle).

⚠️ paddle과 torch는 한 프로세스에서 cuDNN9 DLL 충돌 → 이 모듈은 **인식 워커
서브프로세스**(recognition/worker.py)에서만 import한다. 메인은 매니저
table_cell_detection.detect_table_cells()(파이프 왕복)만 쓴다.
참조: mireye table_cell_detection(직접 import 아님).

모델 경로 config.TABLE_MODEL_DIR, model_name은 inference.yml에서 읽는다.
디바이스 config.REC_DEVICE(빈 값=자동 GPU).
"""
from __future__ import annotations

import warnings

import numpy as np

from ..config import REC_DEVICE, TABLE_CELL_THRESH, TABLE_MODEL_DIR, read_model_name

_det = None


def _load():
    """셀 검출 predictor 1회 로드(전역 singleton). GPU 실패 시 CPU 폴백."""
    global _det
    if _det is not None:
        return _det
    from paddleocr import TableCellsDetection  # lazy

    kw = {"model_dir": TABLE_MODEL_DIR, "threshold": TABLE_CELL_THRESH}
    name = read_model_name(TABLE_MODEL_DIR)
    if name:
        kw["model_name"] = name
    if REC_DEVICE:                       # 빈 값이면 paddleocr 자동 감지(GPU)
        kw["device"] = REC_DEVICE
    try:
        _det = TableCellsDetection(**kw)
    except Exception as e:  # noqa: BLE001 — GPU DLL 문제 시 CPU로 폴백
        if REC_DEVICE == "cpu":
            raise
        warnings.warn(f"셀 검출 GPU 로드 실패({type(e).__name__}: {e}) → CPU 폴백")
        _det = TableCellsDetection(**{**kw, "device": "cpu"})
    return _det


def detect_cells(img: np.ndarray) -> list[list[int]]:
    """BGR 이미지 → 셀 bbox [x, y, w, h] 리스트(원본 좌표계)."""
    det = _load()
    out: list[list[int]] = []
    for r in det.predict(img):           # 결과: dict-like, r["boxes"] = [{coordinate,score,...}]
        for b in r["boxes"]:
            x1, y1, x2, y2 = b["coordinate"]   # xyxy
            x, y = int(round(x1)), int(round(y1))
            w, h = int(round(x2 - x1)), int(round(y2 - y1))
            if w > 0 and h > 0:
                out.append([x, y, w, h])
    return out


if __name__ == "__main__":   # 수동 점검: python -m backend.table_cell_detection.detector <image_path>
    import sys

    import cv2

    data = np.fromfile(sys.argv[1], dtype=np.uint8)
    cells = detect_cells(cv2.imdecode(data, cv2.IMREAD_COLOR))
    print(f"cells={len(cells)}")
    for c in cells[:5]:
        assert len(c) == 4 and c[2] > 0 and c[3] > 0
        print(c)
