"""인식 워커 서브프로세스. paddle을 이 프로세스에서만 import(torch와 DLL 충돌 회피).

⚠️ paddleocr는 modelscope/transformers를 통해 torch를 끌어오는데, torch와 paddle이
같은 프로세스에서 cuDNN9 DLL을 둘 다 못 올린다. 아래에서 torch를 '없는 것'으로 만들어
(modelscope가 find_spec으로만 확인) paddleocr가 torch를 건너뛰게 한다 → paddle만 GPU 로드.

프로토콜(라인 단위, stdin/stdout):
  요청  stdin  : {"path": "<이미지경로>", "boxes": [[x,y,w,h], ...]}\n
  응답  stdout : @@R@@{"texts": [...]} 또는 @@R@@{"error": "..."}\n
  (paddle/glog 로그가 stdout을 오염시킬 수 있어 @@R@@ 마커로 응답만 구분)

실행:  python -m backend.recognition.worker
"""
from __future__ import annotations

import sys

sys.modules["torch"] = None  # paddleocr의 torch 전이 import 차단 (paddle과 cuDNN 충돌 방지)

import json  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from . import MARKER  # noqa: E402
from .recognizer import recognize_crops  # noqa: E402


def _imread(path: str):
    data = np.fromfile(path, dtype=np.uint8)  # 유니코드 경로 대응
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _handle(req: dict) -> dict:
    img = _imread(req["path"])
    if img is None:
        return {"error": f"이미지 로드 실패: {req['path']}"}
    if req.get("op") == "table":          # 테이블 셀 검출 (paddle)
        from ..table_cell_detection.detector import detect_cells  # lazy — 셀 탭 실행 시에만
        return {"cells": detect_cells(img)}
    H, W = img.shape[:2]
    boxes = req.get("boxes", [])
    # 경계로 clamp + 퇴화(빈) crop 스킵 — paddle은 0폭/0높이 입력에서 크래시.
    crops, valid = [], []
    for i, (x, y, w, h) in enumerate(boxes):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        crops.append(img[y0:y1, x0:x1])
        valid.append(i)
    recognized = recognize_crops(crops)
    texts = [""] * len(boxes)
    for i, t in zip(valid, recognized):
        texts[i] = t
    return {"texts": texts}


def main() -> None:
    # stdin/stdout을 바이너리로 다뤄 콘솔 코드페이지(CP949) 인코딩 문제를 피한다.
    # 요청/응답은 UTF-8, paddle/glog 노이즈는 매니저가 마커로 걸러낸다.
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    for raw in stdin:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            out = _handle(json.loads(line))
        except Exception as e:  # noqa: BLE001 — 오류를 응답으로 전달
            out = {"error": f"{type(e).__name__}: {e}"}
        stdout.write((MARKER + json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
        stdout.flush()


if __name__ == "__main__":
    main()
