"""로컬 OCR 파이프라인: detection → recognition.

공개 API:  run_local_ocr(image_path) -> [{"text": str, "poly": [[x,y]*4]}]
무거운 의존성(torch/paddleocr/scipy/opencv) — 미설치 시 import 실패 → app.py가 501로 변환.

self-check:  python -m backend.pipeline <image_path>
"""
from __future__ import annotations

import cv2
import numpy as np

from .config import BOX_PAD_X, BOX_PAD_Y
from .detection import run_detection
from .recognition import recognize


def _imread(path: str) -> "np.ndarray | None":
    """cv2.imread는 Windows에서 한글/유니코드 경로를 못 읽음.
    np.fromfile로 바이트를 읽어 imdecode → 경로 인코딩 문제 회피."""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _pad_box(box, img_w: int, img_h: int) -> list[int]:
    """검출 박스를 우/하단으로 넓힌다(높이 비율, 경계 clamp). x/y는 유지."""
    x, y, w, h = box
    w = min(w + round(h * BOX_PAD_X), img_w - x)
    h = min(h + round(h * BOX_PAD_Y), img_h - y)
    return [x, y, w, h]


def run_local_ocr(image_path: str) -> list[dict]:
    """이미지 → [{"text", "poly": 4점 quad}]. poly는 축정렬 사각형 코너.

    검출(torch)은 메인 프로세스, 인식(paddle)은 워커 서브프로세스에서 수행한다.
    """
    img = _imread(image_path)
    if img is None:
        raise ValueError(f"이미지 로드 실패: {image_path}")
    h, w = img.shape[:2]
    boxes = [_pad_box(b, w, h) for b in run_detection(img)]   # 후처리 패딩
    texts = recognize(image_path, boxes)                 # 워커가 imread+crop+인식
    out = []
    for (x, y, w, h), text in zip(boxes, texts):
        out.append({"text": text,
                    "poly": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]})
    return out


if __name__ == "__main__":
    import sys

    words = run_local_ocr(sys.argv[1])
    print(f"words={len(words)}")
    for w_ in words[:5]:
        assert len(w_["poly"]) == 4 and all(len(p) == 2 for p in w_["poly"])
        print(w_)
