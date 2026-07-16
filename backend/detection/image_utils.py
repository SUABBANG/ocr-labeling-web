"""텍스트 검출 이미지 전처리 (리사이즈 / 정규화 / 패딩)."""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

DEFAULT_DETECTION_CANVAS_SIZE = 1280  # 입력 최대 캔버스 크기 (px)


def resize_aspect_ratio(
    img: np.ndarray,
    square_size: int = DEFAULT_DETECTION_CANVAS_SIZE,
    interpolation: int = cv2.INTER_LINEAR,
    mag_ratio: float = 1,
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """가로세로 비율 유지 리사이즈. 반환 (resized(32배수 패딩), ratio, heatmap 크기(w,h))."""
    height, width, channel = img.shape

    target_size = min(mag_ratio * max(height, width), square_size)
    ratio = target_size / max(height, width)
    target_h, target_w = int(height * ratio), int(width * ratio)
    proc = cv2.resize(img, (target_w, target_h), interpolation=interpolation)

    # 32배수 캔버스에 삽입
    target_h32 = target_h if target_h % 32 == 0 else target_h + (32 - target_h % 32)
    target_w32 = target_w if target_w % 32 == 0 else target_w + (32 - target_w % 32)
    resized = np.zeros((target_h32, target_w32, channel), dtype=img.dtype)
    resized[0:target_h, 0:target_w, :] = proc

    size_heatmap = (int(target_w32 / 2), int(target_h32 / 2))  # score map = 입력의 1/2
    return resized, ratio, size_heatmap


def normalize_mean_variance(
    in_img: np.ndarray,
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
    variance: Tuple[float, float, float] = (0.229, 0.224, 0.225),
) -> np.ndarray:
    """ImageNet mean/variance 정규화 (raw [0,255] float에서 직접)."""
    img = in_img.astype(np.float32, copy=True)
    img -= np.array([m * 255.0 for m in mean], dtype=np.float32)
    img /= np.array([v * 255.0 for v in variance], dtype=np.float32)
    return img


def preprocess_image(
    img: np.ndarray,
    canvas_size: int = DEFAULT_DETECTION_CANVAS_SIZE,
    mag_ratio: float = 1,
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """BGR 이미지 → 리사이즈 → RGB → 정규화 → 텐서(1,3,H,W). 반환 (tensor, ratio, heatmap 크기)."""
    resized, ratio, size_heatmap = resize_aspect_ratio(img, canvas_size, cv2.INTER_LINEAR, mag_ratio)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    normalized = normalize_mean_variance(rgb)
    tensor = normalized.transpose(2, 0, 1)[np.newaxis, ...]
    return tensor, ratio, size_heatmap
