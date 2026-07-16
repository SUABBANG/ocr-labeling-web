"""검출 peak/watershed 후처리 파이프라인."""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

import numpy as np

import logging
from backend.detection._det_utils import (
    LineSplitParams,
    get_score_peak_boxes,
    get_union_overlapped_boxes,
    group_chars_to_words,
)

logger = logging.getLogger("det_model_utils")

def _scale_boxes(
    boxes: List[List[int]],
    scale: float,
) -> List[List[int]]:
    """박스 좌표를 scale 배율로 변환한다."""
    return [
        [int(b[0] * scale), int(b[1] * scale),
         int(b[2] * scale), int(b[3] * scale)]
        for b in boxes
    ]


def _extract_peak_boxes(
    score_text: np.ndarray,
    score_link: np.ndarray,
    *,
    text_threshold: float,
    link_threshold: float,
    char_min_distance: int,
    word_min_distance: int,
    line_split: LineSplitParams | None = None,
) -> Tuple[List[List[int]], List[List[int]], dict[str, Any]]:
    """검출 score map에서 char/link peak boxes를 추출한다."""
    t1_cpu = time.process_time()
    t1_elapsed = time.perf_counter()
    char_boxes_sm, _, char_timing = get_score_peak_boxes(
        score_text,
        text_threshold,
        char_min_distance,
        return_timing=True,
        line_split=line_split,  # 줄 분할은 글자 점수 맵에만 적용
    )
    dt1_cpu = time.process_time() - t1_cpu
    dt1_elapsed = time.perf_counter() - t1_elapsed
    logger.debug(
        "[CPU] char peak+watershed: elapsed=%.3fs, cpu=%.3fs, usage=%.0f%%, boxes=%s",
        dt1_elapsed, dt1_cpu,
        dt1_cpu / dt1_elapsed * 100 if dt1_elapsed > 0 else 0,
        len(char_boxes_sm),
    )

    if not char_boxes_sm:
        return [], [], _prefix_timing("det_char_", char_timing)

    t2_cpu = time.process_time()
    t2_elapsed = time.perf_counter()
    link_boxes_sm, _, link_timing = get_score_peak_boxes(
        score_link,
        link_threshold,
        word_min_distance,
        return_timing=True,
    )
    dt2_cpu = time.process_time() - t2_cpu
    dt2_elapsed = time.perf_counter() - t2_elapsed
    logger.debug(
        "[CPU] link peak+watershed: elapsed=%.3fs, cpu=%.3fs, usage=%.0f%%, boxes=%s",
        dt2_elapsed, dt2_cpu,
        dt2_cpu / dt2_elapsed * 100 if dt2_elapsed > 0 else 0,
        len(link_boxes_sm),
    )

    return char_boxes_sm, link_boxes_sm, {
        **_prefix_timing("det_char_", char_timing),
        **_prefix_timing("det_link_", link_timing),
    }


def _filter_char_boxes_by_size(
    char_boxes_orig: List[List[int]],
    *,
    min_char_w: int,
    min_char_h: int,
    max_char_w: int,
    max_char_h: int,
) -> List[List[int]]:
    """원본 좌표계 char box에 min/max size 필터를 적용한다."""
    return [
        cb for cb in char_boxes_orig
        if cb[2] > min_char_w and cb[3] > min_char_h
        and (max_char_w <= 0 or cb[2] <= max_char_w)
        and (max_char_h <= 0 or cb[3] <= max_char_h)
    ]


def _clamp_box_to_image(
    bx: int, by: int, bw: int, bh: int,
    *, original_width: int, original_height: int,
) -> Tuple[int, int, int, int]:
    """박스를 이미지 경계 내로 제한한다."""
    bx = max(bx, 0)
    by = max(by, 0)
    bw = min(bw, original_width - bx)
    bh = min(bh, original_height - by)
    return bx, by, bw, bh


def _compute_region_confidence(
    score_text: np.ndarray,
    *, bx: int, by: int, bw: int, bh: int, scale: float,
) -> float:
    """원본 좌표계 박스에 대한 score_text 최대 confidence를 계산한다."""
    sx = max(int(bx / scale), 0)
    sy = max(int(by / scale), 0)
    sw = max(int(bw / scale), 1)
    sh = max(int(bh / scale), 1)
    region = score_text[sy:sy + sh, sx:sx + sw]
    return float(np.max(region)) if region.size > 0 else 0.0


def _build_word_boxes_final(
    word_boxes_merged: List[List[int]],
    *, score_text: np.ndarray, scale: float,
    original_width: int, original_height: int,
) -> List[List[Optional[float]]]:
    """병합된 word boxes를 최종 출력 포맷으로 변환한다."""
    word_boxes_final: List[List[Optional[float]]] = []
    for bx, by, bw, bh in word_boxes_merged:
        bx, by, bw, bh = _clamp_box_to_image(
            bx, by, bw, bh,
            original_width=original_width,
            original_height=original_height,
        )
        if bw <= 0 or bh <= 0:
            continue

        conf = _compute_region_confidence(
            score_text, bx=bx, by=by, bw=bw, bh=bh, scale=scale,
        )
        cx = float(bx) + bw / 2.0
        cy = float(by) + bh / 2.0
        word_boxes_final.append([
            float(bx), float(by), float(bw), float(bh),
            cx, cy, conf,
        ])

    word_boxes_final.sort(key=lambda b: (b[1], b[0]))
    return word_boxes_final


def _build_char_boxes_final(
    char_boxes_filtered: List[List[int]],
    *, score_text: np.ndarray, scale: float,
    original_width: int, original_height: int,
) -> List[List[float]]:
    """필터링된 char boxes를 최종 출력 포맷으로 변환한다."""
    char_boxes_final: List[List[float]] = []
    for bx, by, bw, bh in char_boxes_filtered:
        bx, by, bw, bh = _clamp_box_to_image(
            bx, by, bw, bh,
            original_width=original_width,
            original_height=original_height,
        )
        if bw <= 0 or bh <= 0:
            continue

        conf = _compute_region_confidence(
            score_text, bx=bx, by=by, bw=bw, bh=bh, scale=scale,
        )
        char_boxes_final.append([
            float(bx), float(by), float(bw), float(bh), conf,
        ])

    char_boxes_final.sort(key=lambda b: (b[1], b[0]))
    return char_boxes_final


def _extract_filtered_peak_boxes(
    score_text: np.ndarray,
    score_link: np.ndarray,
    *,
    scale: float,
    timing: dict[str, Any],
    text_threshold: float,
    link_threshold: float,
    char_min_distance: int,
    word_min_distance: int,
    min_char_w: int,
    min_char_h: int,
    max_char_w: int,
    max_char_h: int,
    line_split: LineSplitParams | None = None,
) -> tuple[list[list[float]], list[list[float]], bool]:
    """Peak box 추출/스케일/크기 필터 단계를 수행한다."""
    phase_started = time.perf_counter()
    char_boxes_sm, link_boxes_sm, peak_timing = _extract_peak_boxes(
        score_text,
        score_link,
        text_threshold=text_threshold,
        link_threshold=link_threshold,
        char_min_distance=char_min_distance,
        word_min_distance=word_min_distance,
        line_split=line_split,
    )
    timing["det_peak_extract_ms"] = _elapsed_ms(phase_started)
    timing.update(peak_timing)
    if not char_boxes_sm:
        return [], [], False

    phase_started = time.perf_counter()
    char_boxes_orig = _scale_boxes(char_boxes_sm, scale)
    link_boxes_orig = _scale_boxes(link_boxes_sm, scale)
    char_boxes_filtered = _filter_char_boxes_by_size(
        char_boxes_orig,
        min_char_w=min_char_w,
        min_char_h=min_char_h,
        max_char_w=max_char_w,
        max_char_h=max_char_h,
    )
    timing["det_scale_filter_ms"] = _elapsed_ms(phase_started)
    timing["det_char_box_count"] = len(char_boxes_filtered)
    timing["det_link_box_count"] = len(link_boxes_orig)
    return char_boxes_filtered, link_boxes_orig, True


def _group_word_boxes_with_timing(
    char_boxes_filtered: list[list[float]],
    link_boxes_orig: list[list[float]],
    *,
    timing: dict[str, Any],
    min_char_w: int,
    min_char_h: int,
    max_height_ratio: float,
    max_chars_per_word: int,
) -> list[list[Optional[float]]]:
    """Char boxes를 word boxes로 묶고 CPU timing을 기록한다."""
    t5_cpu = time.process_time()
    t5_elapsed = time.perf_counter()
    word_boxes_raw, _ = group_chars_to_words(
        char_boxes_filtered, link_boxes_orig,
        min_char_w=min_char_w,
        min_char_h=min_char_h,
        max_height_ratio=max_height_ratio,
        max_chars_per_word=max_chars_per_word,
    )
    dt5_cpu = time.process_time() - t5_cpu
    dt5_elapsed = time.perf_counter() - t5_elapsed
    timing["det_word_grouping_ms"] = round(dt5_elapsed * 1000, 3)
    logger.debug(
        "[CPU] word grouping: elapsed=%.3fs, cpu=%.3fs, usage=%.0f%%, chars=%s, words=%s",
        dt5_elapsed, dt5_cpu,
        dt5_cpu / max(dt5_elapsed, 1e-6) * 100,
        len(char_boxes_filtered), len(word_boxes_raw),
    )
    return word_boxes_raw


def _merge_word_boxes_with_timing(
    word_boxes_raw: list[list[Optional[float]]],
    union_overlap_ratio: float,
    timing: dict[str, Any],
) -> list[list[Optional[float]]]:
    """겹치는 word boxes를 병합하고 CPU timing을 기록한다."""
    t6_cpu = time.process_time()
    t6_elapsed = time.perf_counter()
    word_boxes_merged = get_union_overlapped_boxes(
        word_boxes_raw, union_overlap_ratio,
    )
    dt6_cpu = time.process_time() - t6_cpu
    dt6_elapsed = time.perf_counter() - t6_elapsed
    timing["det_overlap_union_ms"] = round(dt6_elapsed * 1000, 3)
    logger.debug(
        "[CPU] overlap union: elapsed=%.3fs, cpu=%.3fs, usage=%.0f%%, before=%s, after=%s",
        dt6_elapsed, dt6_cpu,
        dt6_cpu / max(dt6_elapsed, 1e-6) * 100,
        len(word_boxes_raw), len(word_boxes_merged),
    )
    return word_boxes_merged


def _build_final_boxes_with_timing(
    word_boxes_merged: list[list[Optional[float]]],
    char_boxes_filtered: list[list[float]],
    *,
    score_text: np.ndarray,
    scale: float,
    original_width: int,
    original_height: int,
    timing: dict[str, Any],
) -> tuple[list[list[Optional[float]]], list[list[float]]]:
    """최종 word/char box 포맷을 만들고 timing을 기록한다."""
    phase_started = time.perf_counter()
    word_boxes_final = _build_word_boxes_final(
        word_boxes_merged,
        score_text=score_text,
        scale=scale,
        original_width=original_width,
        original_height=original_height,
    )
    timing["det_build_word_final_ms"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()
    char_boxes_final = _build_char_boxes_final(
        char_boxes_filtered,
        score_text=score_text,
        scale=scale,
        original_width=original_width,
        original_height=original_height,
    )
    timing["det_build_char_final_ms"] = _elapsed_ms(phase_started)
    return word_boxes_final, char_boxes_final


def peak_postprocess(
    score_text: np.ndarray,
    score_link: np.ndarray,
    original_width: int,
    original_height: int,
    ratio: float = 1.0,
    ratio_net: int = 2,
    text_threshold: float = 0.4,
    link_threshold: float = 0.2,
    word_min_distance: int = 5,
    char_min_distance: int = 1,
    min_char_w: int = 3,
    min_char_h: int = 3,
    max_char_w: int = 0,
    max_char_h: int = 0,
    max_height_ratio: float = 3.0,
    union_overlap_ratio: float = 0.4,
    max_chars_per_word: int = 25,
    return_timing: bool = False,
    line_split: LineSplitParams | None = None,
) -> Tuple[List[List[Optional[float]]], List[List[float]]] | tuple[
    List[List[Optional[float]]],
    List[List[float]],
    dict[str, Any],
]:
    """검출 peak+watershed 후처리 파이프라인.

    word_range_offset은 Core CPU 측 공통 후처리에서 적용한다.
    """
    t0_elapsed = time.perf_counter()
    t0_cpu = time.process_time()
    timing: dict[str, Any] = {}

    scale = ratio_net / ratio

    char_boxes_filtered, link_boxes_orig, has_peak_boxes = _extract_filtered_peak_boxes(
        score_text,
        score_link,
        scale=scale,
        timing=timing,
        text_threshold=text_threshold,
        link_threshold=link_threshold,
        char_min_distance=char_min_distance,
        word_min_distance=word_min_distance,
        min_char_w=min_char_w,
        min_char_h=min_char_h,
        max_char_w=max_char_w,
        max_char_h=max_char_h,
        line_split=line_split,
    )
    if not has_peak_boxes:
        logger.debug(
            "peak_postprocess: elapsed=%.3fs, no char boxes found",
            time.perf_counter() - t0_elapsed,
        )
        return _postprocess_return([], [], timing, return_timing)
    if not char_boxes_filtered:
        return _postprocess_return([], [], timing, return_timing)

    word_boxes_raw = _group_word_boxes_with_timing(
        char_boxes_filtered,
        link_boxes_orig,
        timing=timing,
        min_char_w=min_char_w,
        min_char_h=min_char_h,
        max_height_ratio=max_height_ratio,
        max_chars_per_word=max_chars_per_word,
    )
    if not word_boxes_raw:
        return _postprocess_return([], [], timing, return_timing)

    word_boxes_merged = _merge_word_boxes_with_timing(
        word_boxes_raw,
        union_overlap_ratio,
        timing,
    )

    word_boxes_final, char_boxes_final = _build_final_boxes_with_timing(
        word_boxes_merged,
        char_boxes_filtered,
        score_text=score_text,
        scale=scale,
        original_width=original_width,
        original_height=original_height,
        timing=timing,
    )

    total_elapsed = time.perf_counter() - t0_elapsed
    total_cpu = time.process_time() - t0_cpu
    timing["peak_postprocess_total_ms"] = round(total_elapsed * 1000, 3)
    logger.debug(
        "[CPU] peak_postprocess 합계: elapsed=%.3fs, cpu=%.3fs, usage=%.0f%%, "
        "words=%s, chars=%s",
        total_elapsed, total_cpu,
        total_cpu / max(total_elapsed, 1e-6) * 100,
        len(word_boxes_final), len(char_boxes_final),
    )

    return _postprocess_return(word_boxes_final, char_boxes_final, timing, return_timing)


def _postprocess_return(
    word_boxes: List[List[Optional[float]]],
    char_boxes: List[List[float]],
    timing: dict[str, Any],
    return_timing: bool,
) -> Tuple[List[List[Optional[float]]], List[List[float]]] | tuple[
    List[List[Optional[float]]],
    List[List[float]],
    dict[str, Any],
]:
    if return_timing:
        return word_boxes, char_boxes, timing
    return word_boxes, char_boxes


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _prefix_timing(prefix: str, timing: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}{key}": value for key, value in timing.items()}
