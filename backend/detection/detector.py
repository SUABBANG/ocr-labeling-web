"""텍스트 검출: 이미지 → axis-aligned word box [x,y,w,h] 리스트.

arch/전처리/후처리는 같은 패키지에 포함. backbone은 MobileNetV3-Large.
후처리 파라미터 기본값은 재현성을 위해 고정.
"""
from __future__ import annotations

import numpy as np
import torch

from ..config import DET_MODEL_PATH
from .arch import build_detector
from .image_utils import preprocess_image
from .postprocess import peak_postprocess
from ._det_utils import LineSplitParams, copy_state_dict

_CANVAS_SIZE = 1280
_MAG_RATIO = 1.0
_DET_KW = dict(
    ratio_net=2, text_threshold=0.4, link_threshold=0.2,
    word_min_distance=5, char_min_distance=1,
    min_char_w=3, min_char_h=3, max_char_w=0, max_char_h=0,
    max_height_ratio=3.0, union_overlap_ratio=0.4, max_chars_per_word=25,
    line_split=LineSplitParams(enabled=True, valley_ratio=0.55,
                               min_band_frac=0.30, min_height=5),
)

_device = None
_model = None


def _load():
    """검출 모델을 1회 로드(전역 singleton)."""
    global _model, _device
    if _model is not None:
        return _model
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_detector(backbone="MOBILENET_V3_LARGE", pretrained=False)
    state = torch.load(DET_MODEL_PATH, map_location="cpu", weights_only=True)
    model.load_state_dict(copy_state_dict(state))
    model.eval().to(_device)
    _model = model
    return model


def run_detection(img_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """검출 forward + 후처리 → word box [x,y,w,h] 리스트(읽기순)."""
    model = _load()
    tensor, ratio, _ = preprocess_image(img_bgr, _CANVAS_SIZE, _MAG_RATIO)
    x = torch.from_numpy(tensor).to(_device)
    with torch.no_grad():
        y, _feat = model(x)          # y: (1, H, W, 2)
    score = y[0].detach().cpu().numpy()
    h, w = img_bgr.shape[:2]
    word_boxes, _chars = peak_postprocess(
        score[:, :, 0], score[:, :, 1],
        original_width=w, original_height=h, ratio=ratio, **_DET_KW,
    )
    return [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in word_boxes]
