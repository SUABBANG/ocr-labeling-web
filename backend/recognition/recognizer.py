"""인식 모델 로직 (paddle 사용).

⚠️ paddle과 torch는 같은 프로세스에서 공존 불가(둘 다 cuDNN9 번들 → DLL 충돌).
그래서 이 모듈은 **인식 워커 서브프로세스**(worker.py)에서만 import한다.
메인 프로세스는 recognition/__init__.py의 recognize()(서브프로세스 관리)만 쓴다.

모델 경로는 config.REC_MODEL_DIR, 디바이스는 config.REC_DEVICE(빈 값=자동 GPU).
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import numpy as np

from ..config import REC_DEVICE, REC_MODEL_DIR

_rec = None


def _model_name() -> "str | None":
    """inference.yml의 model_name을 읽는다.
    라이브러리 기본 model_name과 config가 달라 발생하는 mismatch 오류 방지."""
    yml = Path(REC_MODEL_DIR) / "inference.yml"
    try:
        m = re.search(r"model_name:\s*(\S+)", yml.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


def _load():
    """인식 predictor를 1회 로드(전역 singleton). GPU 실패 시 CPU 폴백."""
    global _rec
    if _rec is not None:
        return _rec
    from paddleocr import TextRecognition  # lazy

    kw = {"model_dir": REC_MODEL_DIR}
    name = _model_name()
    if name:
        kw["model_name"] = name
    if REC_DEVICE:                       # 빈 값이면 paddleocr 자동 감지(GPU)
        kw["device"] = REC_DEVICE
    try:
        _rec = TextRecognition(**kw)
    except Exception as e:  # noqa: BLE001 — GPU DLL 문제 시 CPU로 폴백
        if REC_DEVICE == "cpu":
            raise
        warnings.warn(f"인식 GPU 로드 실패({type(e).__name__}: {e}) → CPU 폴백")
        _rec = TextRecognition(**{**kw, "device": "cpu"})
    return _rec


def recognize_crops(crops: list[np.ndarray]) -> list[str]:
    """crop(BGR) 리스트 → 텍스트 리스트."""
    if not crops:
        return []
    rec = _load()
    results = rec.predict(crops)   # 결과: dict-like 리스트
    return [str(r.get("rec_text", "")) for r in results]
