"""
텍스트 검출 모델 유틸리티.

가중치 파일 탐색, state_dict 정리, 읽기 순서 정렬,
score map 기반 박스 추출 등 검출 모델에 필요한 공통 유틸리티.
"""
from __future__ import annotations

import time
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import numpy as np

import logging

logger = logging.getLogger("det_model_utils")

_UNION_OVERLAPPED_BOX_FALLBACK_LIMIT = 500

# 검출 후처리를 여러 페이지 병렬 실행할 때 native 수치 라이브러리를 워커당 single-thread로
# 유지해 OpenMP/BLAS oversubscription을 방지한다.
for _THREAD_ENV_NAME in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_THREAD_ENV_NAME, "1")


# ------------------------------------------------------------------
# 줄 분할(line-split) 파라미터
# 세로로 인접한 두 줄이 한 문자 박스로 붙는 경우, 줄 사이 수평 투영 골(valley)이 뚜렷하면
# 그 지점에서 줄을 나눈다. score_text 추출에만 적용. 값은 검출 설정(line_split_*)에서 관리.
@dataclass(frozen=True)
class LineSplitParams:
    enabled: bool = False
    valley_ratio: float = 0.55   # 골 깊이 <= peak×ratio 일 때만 줄 경계로 인정
    min_band_frac: float = 0.30  # 분할 후 각 줄 밴드 최소 높이(세그 높이 대비)
    min_height: int = 5          # 최소 세그 높이(px). score map ~5.3x downscale라 한 줄 ~7px
    min_prominence: float = 1.3  # split 위/아래 밴드 피크가 각각 골값×이 배수 이상이어야 진짜 줄 골(한 줄 roof 오분할 방지)


_LINE_SPLIT_DISABLED = LineSplitParams(enabled=False)


def copy_state_dict(state_dict: dict) -> OrderedDict:
    """
    DataParallel 등에서 저장된 state_dict의 'module.' 접두사를 제거합니다.
    """
    if not state_dict:
        return OrderedDict()

    first_key = next(iter(state_dict))
    if first_key.startswith("module"):
        start_idx = 1
    else:
        start_idx = 0

    new_state_dict = OrderedDict()
    for k, v in state_dict.items():
        name = ".".join(k.split(".")[start_idx:])
        new_state_dict[name] = v
    return new_state_dict


def sort_reading_order_indices(
    boxes: List[List[Optional[float]]],
) -> List[int]:
    """
    바운딩 박스를 읽기 순서(위->아래, 왼->오른쪽)로 정렬한 인덱스를 반환합니다.

    Args:
        boxes: [x, y, w, h, ...] 형식의 박스 리스트

    Returns:
        정렬된 인덱스 리스트
    """
    if not boxes:
        return []
    return sorted(
        range(len(boxes)),
        key=lambda i: (
            (boxes[i][1] or 0) + (boxes[i][3] or 0) / 2,  # cy = y + h/2
            (boxes[i][0] or 0) + (boxes[i][2] or 0) / 2,  # cx = x + w/2
        ),
    )


# ------------------------------------------------------------------
# Score map -> 박스 추출
# ------------------------------------------------------------------


def get_score_peak_boxes(
    score: np.ndarray,
    threshold: float,
    min_distance: int,
    *,
    return_timing: bool = False,
    line_split: "LineSplitParams | None" = None,
) -> Tuple[List[List[int]], List[Tuple[int, int]]] | tuple[
    List[List[int]],
    List[Tuple[int, int]],
    dict[str, Any],
]:
    """
    Score map에서 connected component 기반 바운딩 박스를 추출합니다.

    이진화된 score mask에서 connected component labeling으로 영역을 추출한다.
    겹치는 영역을 watershed로 분할하지 않아, 수평으로 인접한 문자가 하나의
    영역으로 유지된다. 상하로 연결된 영역은 수평 투영 기반으로 분리한다.
    """
    try:
        from scipy import ndimage

        t0 = time.perf_counter()
        timing: dict[str, Any] = {}

        # 1. 이진화
        phase_started = time.perf_counter()
        score_mask = score > threshold
        timing["score_mask_ms"] = _elapsed_ms(phase_started)
        if not np.any(score_mask):
            return _score_peak_return([], [], timing, return_timing)

        # 2. connected component labeling
        cc_started = time.perf_counter()
        labels, num_features = ndimage.label(score_mask)
        timing["connected_component_ms"] = _elapsed_ms(cc_started)

        if num_features == 0:
            return _score_peak_return([], [], timing, return_timing)

        # 3. 수평 투영 기반으로 상하 연결 영역 분리 + bbox 추출
        split_started = time.perf_counter()
        slices = ndimage.find_objects(labels)
        boxes: List[List[int]] = []
        peaks: List[Tuple[int, int]] = []

        params = line_split or _LINE_SPLIT_DISABLED
        for i, s in enumerate(slices):
            if s is None:
                continue
            region = labels[s] == (i + 1)
            sub_boxes, sub_peaks = _split_cc_vertical(
                region, s, score_region=score[s], line_split=params,
            )
            boxes.extend(sub_boxes)
            peaks.extend(sub_peaks)

        timing["split_bbox_ms"] = _elapsed_ms(split_started)
        timing["score_peak_total_ms"] = _elapsed_ms(t0)

        logger.debug(
            "get_score_peak_boxes: total=%.3fs, cc=%.1fms, "
            "split_bbox=%.1fms, boxes=%s, peaks=%s",
            timing["score_peak_total_ms"] / 1000,
            timing["connected_component_ms"],
            timing["split_bbox_ms"],
            len(boxes),
            len(peaks),
        )
        return _score_peak_return(boxes, peaks, timing, return_timing)

    except (ImportError, RuntimeError, ValueError, OSError) as e:
        logger.error("get_score_peak_boxes 오류: %s", e)
        return _score_peak_return([], [], {}, return_timing)


def _split_cc_vertical(
    region: np.ndarray,
    label_slice: Tuple[slice, slice],
    *,
    score_region: np.ndarray | None = None,
    line_split: LineSplitParams = _LINE_SPLIT_DISABLED,
) -> Tuple[List[List[int]], List[Tuple[int, int]]]:
    """Connected component 하나를 수평 투영 기반으로 상하 분리한다.

    높이 > 너비인 세그먼트를 투영 최솟값 지점에서 재귀적으로 분할한다.
    line_split.enabled 이면, 분할 전에 줄 사이 수평 투영 골이 뚜렷한 지점에서
    줄 단위로 먼저 나눈다(_split_lines_by_valley).

    valley 지표는 component 내 행별 score 합(∑score, region 마스킹). 글자 행은
    score mass가 크고 줄 사이는 작아 뚜렷한 골이 생긴다. score_region이 없으면
    이진 마스크 행별 활성 열 수로 폴백한다.
    """
    # 행별 score 합(score mass) = 글자 밀도. 줄 사이에서 뚜렷한 골을 만든다.
    if score_region is not None:
        valley_metric = np.where(region, score_region, 0.0).sum(axis=1).astype(np.float64)
    else:
        valley_metric = region.sum(axis=1).astype(np.float64)
    if line_split.enabled:
        line_bands = _split_lines_by_valley(valley_metric, 0, len(valley_metric), line_split)
    else:
        line_bands = [(0, len(valley_metric))]
    segments: List[Tuple[int, int]] = []
    for band_start, band_end in line_bands:
        segments.extend(_ensure_horizontal(valley_metric, region, band_start, band_end))
    return _segments_to_boxes(segments, region, label_slice)


def _split_lines_by_valley(
    h_proj: np.ndarray,
    start: int,
    end: int,
    params: LineSplitParams,
) -> List[Tuple[int, int]]:
    """세그먼트를 줄 사이 수평 투영 골에서 재귀적으로 나눈다(가로 폭 무관).

    _ensure_horizontal과 달리 "높이 > 너비" 조건을 보지 않는다. 대신:
      - 골은 가장자리 마진(밴드 최소 높이) 안쪽에서만 찾는다(얇은 조각 방지).
      - 골 깊이가 peak의 valley_ratio 이하일 때만 줄 경계로 인정한다.
    이로써 한 줄 내부의 얕은 굴곡으로는 안 쪼개지고, 줄 사이의 뚜렷한 골에서만 나뉜다.
    """
    seg_h = end - start
    min_height = params.min_height
    if seg_h < max(min_height * 2, 4):
        return [(start, end)]

    sub_proj = h_proj[start:end]
    peak_val = float(sub_proj.max())
    if peak_val <= 0:
        return [(start, end)]

    margin = max(int(seg_h * params.min_band_frac), min_height)
    if 2 * margin >= seg_h:
        return [(start, end)]

    interior = sub_proj[margin:seg_h - margin]
    if interior.size == 0:
        return [(start, end)]

    rel_min = int(np.argmin(interior)) + margin
    if sub_proj[rel_min] > peak_val * params.valley_ratio:
        return [(start, end)]

    valley_v = sub_proj[rel_min]
    left_peak = sub_proj[:rel_min].max()
    right_peak = sub_proj[rel_min:].max()
    if (left_peak < valley_v * params.min_prominence
            or right_peak < valley_v * params.min_prominence):
        return [(start, end)]

    split_row = start + rel_min
    if split_row <= start or split_row >= end - 1:
        return [(start, end)]

    return (
        _split_lines_by_valley(h_proj, start, split_row, params)
        + _split_lines_by_valley(h_proj, split_row, end, params)
    )


def _ensure_horizontal(
    h_proj: np.ndarray,
    region: np.ndarray,
    start: int,
    end: int,
) -> List[Tuple[int, int]]:
    """높이 > 너비인 세그먼트를 투영 최솟값에서 재귀 분할한다."""
    seg_h = end - start
    if seg_h < 2:
        return [(start, end)]

    sub_region = region[start:end, :]
    seg_w = int(sub_region.any(axis=0).sum())

    # 높이 <= 너비면 분할 불필요
    if seg_h <= max(seg_w, 1):
        return [(start, end)]

    sub_proj = h_proj[start:end]
    peak_val = sub_proj.max()
    min_idx = int(np.argmin(sub_proj))

    # valley가 peak의 50% 이상이면 유의미한 골이 아님 → 분할 중단
    if peak_val == 0 or sub_proj[min_idx] > peak_val * 0.5:
        return [(start, end)]

    split_row = start + min_idx

    # 분할점이 양 끝이면 분할 불가
    if split_row <= start or split_row >= end - 1:
        return [(start, end)]

    left = _ensure_horizontal(h_proj, region, start, split_row)
    right = _ensure_horizontal(h_proj, region, split_row, end)
    return left + right


def _segments_to_boxes(
    segments: List[Tuple[int, int]],
    region: np.ndarray,
    label_slice: Tuple[slice, slice],
) -> Tuple[List[List[int]], List[Tuple[int, int]]]:
    """세그먼트 목록을 [x, y, w, h] 박스와 centroid로 변환한다."""
    abs_y0 = label_slice[0].start
    abs_x0 = label_slice[1].start

    boxes: List[List[int]] = []
    peaks: List[Tuple[int, int]] = []

    for seg_start, seg_end in segments:
        sub_region = region[seg_start:seg_end, :]
        cols = np.where(sub_region.any(axis=0))[0]
        if len(cols) == 0:
            continue
        col_start = int(cols[0])
        col_end = int(cols[-1]) + 1
        bx = abs_x0 + col_start
        by = abs_y0 + seg_start
        bw = col_end - col_start
        bh = seg_end - seg_start
        boxes.append([bx - 1, by - 1, bw, bh])
        peaks.append((bx + bw // 2, by + bh // 2))

    return boxes, peaks


def _score_peak_return(
    boxes: List[List[int]],
    peaks: List[Tuple[int, int]],
    timing: dict[str, Any],
    return_timing: bool,
):
    if return_timing:
        return boxes, peaks, timing
    return boxes, peaks


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


# ------------------------------------------------------------------
# char -> word grouping
# ------------------------------------------------------------------


def _filter_valid_char_boxes(
    char_boxes: List[List[int]],
    min_char_w: int,
    min_char_h: int,
) -> List[List[int]]:
    """최소 크기 조건을 만족하는 문자 박스만 남긴다."""
    return [
        cb for cb in char_boxes
        if cb[2] > min_char_w and cb[3] > min_char_h
    ]


def _find_link_overlap_indices_for_candidates(
    range_arr: np.ndarray,
    candidate_indices: np.ndarray,
    lx1: float,
    ly1: float,
    lx2: float,
    ly2: float,
    l_cy: float,
) -> list[int]:
    """후보 group index 중 link와 겹치는 index를 x/y 순서로 반환한다."""
    if candidate_indices.size < 2:
        return []

    coords = range_arr[candidate_indices]
    c_x1 = coords[:, 0]
    c_y1 = coords[:, 1]
    c_w = coords[:, 2]
    c_h = coords[:, 3]
    c_x2 = c_x1 + c_w
    c_y2 = c_y1 + c_h

    hit_local = np.flatnonzero(
        (np.maximum(c_x1, lx1) < np.minimum(c_x2, lx2))
        & (np.maximum(c_y1, ly1) < np.minimum(c_y2, ly2))
        & (c_y1 + c_h / 4 <= l_cy)
        & (l_cy <= c_y1 + c_h * 3 / 4)
    )
    if hit_local.size < 2:
        return []

    hit_indices = candidate_indices[hit_local]
    return sorted(
        (int(idx) for idx in hit_indices),
        key=lambda idx: (range_arr[idx, 0], range_arr[idx, 1]),
    )


def _x_prefilter_link_candidates(
    active_mask: np.ndarray,
    range_arr: np.ndarray,
    x1_order: np.ndarray,
    x1_sorted: np.ndarray,
    lx1: float,
    lx2: float,
) -> np.ndarray:
    """link x 범위와 겹칠 수 있는 active char 후보를 반환한다.

    후보 조건은 기존 x-overlap 판정 ``c_x1 < lx2 and c_x2 > lx1``과 같다.
    ``x1``은 merge 후에도 감소하지 않는 contract(왼쪽 char index에 병합)라서
    초기 ``x1_order``를 재사용할 수 있다. ``x2``는 merge로 증가할 수 있으므로
    현재 ``range_arr`` 값으로 다시 필터링한다.
    """
    upper = int(np.searchsorted(x1_sorted, lx2, side="left"))
    if upper <= 0:
        return np.empty(0, dtype=np.int64)

    candidates = x1_order[:upper]
    if candidates.size == 0:
        return candidates

    c_x2 = range_arr[candidates, 0] + range_arr[candidates, 2]
    mask = active_mask[candidates] & (c_x2 > lx1)
    return candidates[mask]


def group_chars_to_words(
    char_boxes: List[List[int]],
    link_boxes: List[List[int]],
    min_char_w: int = 3,
    min_char_h: int = 3,
    max_height_ratio: float = 3.0,
    adjust_subbox_y: bool = True,
    max_chars_per_word: int = 25,
) -> Tuple[List[List[int]], List[List[List[int]]]]:
    """Link score 기반으로 문자 박스를 단어 박스로 그룹핑한다."""
    char_boxes = _filter_valid_char_boxes(char_boxes, min_char_w, min_char_h)
    if not char_boxes:
        return [], []

    group_count = len(char_boxes)
    group_x1 = np.asarray([box[0] for box in char_boxes], dtype=np.float64)
    group_y1 = np.asarray([box[1] for box in char_boxes], dtype=np.float64)
    group_x2 = group_x1 + np.asarray([box[2] for box in char_boxes], dtype=np.float64)
    group_y2 = group_y1 + np.asarray([box[3] for box in char_boxes], dtype=np.float64)
    group_subboxes: list[list[tuple[int, int, int, int]]] = [
        [(int(cx), int(cy), int(cw), int(ch))]
        for cx, cy, cw, ch in char_boxes
    ]

    sorted_links = sorted(link_boxes, key=lambda lr: (lr[0], lr[1]))
    # link가 없으면 병합 없이 각 char 박스가 그대로 단어가 된다. active_mask를 블록 밖에서
    # 초기화해야 link_boxes=0(희박한 검출) 케이스에서 미할당 참조(UnboundLocalError)를 막는다.
    active_mask = np.ones(group_count, dtype=bool)

    if sorted_links:
        link_arr = np.array(sorted_links, dtype=np.float64)
        link_x1 = link_arr[:, 0]
        link_y1 = link_arr[:, 1]
        link_x2 = link_arr[:, 0] + link_arr[:, 2]
        link_y2 = link_arr[:, 1] + link_arr[:, 3]
        link_cy = link_y1 + link_arr[:, 3] / 2

        range_arr = _build_group_range_array(group_x1, group_y1, group_x2, group_y2)
        x1_order = np.argsort(range_arr[:, 0], kind="stable")
        x1_sorted = range_arr[x1_order, 0]
        for li in range(len(sorted_links)):
            candidate_indices = _x_prefilter_link_candidates(
                active_mask,
                range_arr,
                x1_order,
                x1_sorted,
                link_x1[li],
                link_x2[li],
            )
            overlapped = _find_link_overlap_indices_for_candidates(
                range_arr,
                candidate_indices,
                link_x1[li],
                link_y1[li],
                link_x2[li],
                link_y2[li],
                link_cy[li],
            )
            if not _can_merge_group_indices(
                overlapped,
                group_subboxes,
                max_height_ratio,
                max_chars_per_word,
            ):
                continue

            idx_initial, removed_indices = _merge_group_indices(
                overlapped,
                group_x1,
                group_y1,
                group_x2,
                group_y2,
                group_subboxes,
                adjust_subbox_y,
            )
            range_arr[idx_initial] = [
                group_x1[idx_initial],
                group_y1[idx_initial],
                group_x2[idx_initial] - group_x1[idx_initial],
                group_y2[idx_initial] - group_y1[idx_initial],
            ]
            if removed_indices:
                active_mask[removed_indices] = False

    return _build_group_outputs(
        active_mask,
        group_x1,
        group_y1,
        group_x2,
        group_y2,
        group_subboxes,
        min_char_w,
        min_char_h,
    )


def _build_group_range_array(
    group_x1: np.ndarray,
    group_y1: np.ndarray,
    group_x2: np.ndarray,
    group_y2: np.ndarray,
) -> np.ndarray:
    """active group overlap 판정용 [x,y,w,h] 배열을 만든다."""
    return np.column_stack(
        (
            group_x1,
            group_y1,
            group_x2 - group_x1,
            group_y2 - group_y1,
        )
    )


def _can_merge_group_indices(
    group_indices: list[int],
    group_subboxes: list[list[tuple[int, int, int, int]]],
    max_height_ratio: float,
    max_chars_per_word: int,
) -> bool:
    """현재 group index들이 legacy guard 조건상 병합 가능한지 판단한다."""
    if len(group_indices) < 2:
        return False

    heights = [group_subboxes[idx][0][3] for idx in group_indices]
    max_h = max(heights)
    min_h = min(heights)
    if min_h <= 0 or max_h / min_h >= max_height_ratio:
        return False

    if max_chars_per_word > 0:
        total_subs = sum(len(group_subboxes[idx]) for idx in group_indices)
        if total_subs > max_chars_per_word:
            return False

    return True


def _merge_group_indices(
    group_indices: list[int],
    group_x1: np.ndarray,
    group_y1: np.ndarray,
    group_x2: np.ndarray,
    group_y2: np.ndarray,
    group_subboxes: list[list[tuple[int, int, int, int]]],
    adjust_subbox_y: bool,
) -> tuple[int, list[int]]:
    """legacy merge와 같은 root 선택으로 group들을 병합한다."""
    idx_initial = group_indices[0]

    merged_x1 = min(float(group_x1[idx]) for idx in group_indices)
    merged_y1 = min(float(group_y1[idx]) for idx in group_indices)
    merged_x2 = max(float(group_x2[idx]) for idx in group_indices)
    merged_y2 = max(float(group_y2[idx]) for idx in group_indices)
    merged_h = int(merged_y2 - merged_y1)

    merged_subboxes: list[tuple[int, int, int, int]] = []
    for idx in group_indices:
        merged_subboxes.extend(group_subboxes[idx])
    if adjust_subbox_y:
        merged_subboxes = [
            (sbx, int(merged_y1), sbw, merged_h)
            for (sbx, _sby, sbw, _sbh) in merged_subboxes
        ]

    group_x1[idx_initial] = merged_x1
    group_y1[idx_initial] = merged_y1
    group_x2[idx_initial] = merged_x2
    group_y2[idx_initial] = merged_y2
    group_subboxes[idx_initial] = merged_subboxes

    removed_indices = group_indices[1:]
    for idx in removed_indices:
        group_subboxes[idx] = []
    return idx_initial, removed_indices


def _build_group_outputs(
    active_mask: np.ndarray,
    group_x1: np.ndarray,
    group_y1: np.ndarray,
    group_x2: np.ndarray,
    group_y2: np.ndarray,
    group_subboxes: list[list[tuple[int, int, int, int]]],
    min_char_w: int,
    min_char_h: int,
) -> Tuple[List[List[int]], List[List[List[int]]]]:
    """최종 active group을 word/subbox 출력으로 변환한다."""
    word_boxes: List[List[int]] = []
    sub_boxes_list: List[List[List[int]]] = []
    for idx in np.flatnonzero(active_mask):
        bx = int(group_x1[idx])
        by = int(group_y1[idx])
        bw = int(group_x2[idx] - group_x1[idx])
        bh = int(group_y2[idx] - group_y1[idx])
        if bw > min_char_w and bh > min_char_h:
            word_boxes.append([bx, by, bw, bh])
            sub_boxes_list.append(group_subboxes[int(idx)])
    return word_boxes, sub_boxes_list


def get_union_overlapped_boxes(
    boxes: List[List[int]],
    overlap_ratio: float = 0.4,
) -> List[List[int]]:
    """겹치는 박스들을 면적 비율 기준으로 합친다(union)."""
    n = len(boxes)
    if n == 0:
        return []
    if n > _UNION_OVERLAPPED_BOX_FALLBACK_LIMIT:
        logger.warning(
            "get_union_overlapped_boxes fallback: box_count=%s exceeds limit=%s; "
            "skip iterative union",
            n,
            _UNION_OVERLAPPED_BOX_FALLBACK_LIMIT,
        )
        return _normalize_boxes(boxes)

    arr = np.array(boxes, dtype=np.float64)
    x1 = arr[:, 0]
    y1 = arr[:, 1]
    x2 = x1 + arr[:, 2]
    y2 = y1 + arr[:, 3]

    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    changed = True
    while changed:
        changed = False

        # 라운드마다 각 원소의 현재 root를 파이썬 find로 한 번만 계산하고, 그룹 bbox 집계와
        # eff 배열 확장은 numpy scatter-reduce(minimum/maximum.at) + gather로 벡터화한다.
        # 기존 파이썬 루프/컴프리헨션(원소당 find 5회)과 결과는 동일하다.
        roots_arr = np.fromiter((find(i) for i in range(n)), dtype=np.int64, count=n)

        group_x1 = np.full(n, np.inf)
        group_y1 = np.full(n, np.inf)
        group_x2 = np.full(n, -np.inf)
        group_y2 = np.full(n, -np.inf)
        np.minimum.at(group_x1, roots_arr, x1)
        np.minimum.at(group_y1, roots_arr, y1)
        np.maximum.at(group_x2, roots_arr, x2)
        np.maximum.at(group_y2, roots_arr, y2)

        eff_x1 = group_x1[roots_arr]
        eff_y1 = group_y1[roots_arr]
        eff_x2 = group_x2[roots_arr]
        eff_y2 = group_y2[roots_arr]
        eff_areas = (eff_x2 - eff_x1) * (eff_y2 - eff_y1)

        roots = sorted(set(roots_arr.tolist()))
        for a, b in _find_overlapping_root_pairs(
            roots,
            eff_x1,
            eff_y1,
            eff_x2,
            eff_y2,
            eff_areas,
            overlap_ratio,
        ):
            if find(a) == find(b):
                continue
            union(a, b)
            changed = True

    groups: dict = {}
    for i in range(n):
        r = find(i)
        if r not in groups:
            groups[r] = [x1[i], y1[i], x2[i], y2[i]]
        else:
            g = groups[r]
            g[0] = min(g[0], x1[i])
            g[1] = min(g[1], y1[i])
            g[2] = max(g[2], x2[i])
            g[3] = max(g[3], y2[i])

    return [
        [int(gx1), int(gy1), int(gx2 - gx1), int(gy2 - gy1)]
        for gx1, gy1, gx2, gy2 in groups.values()
    ]


def _normalize_boxes(boxes: List[List[int]]) -> List[List[int]]:
    """fallback 경로에서 입력 bbox를 int [x, y, w, h] 계약으로 정규화한다."""
    return [
        [
            int(box[0]),
            int(box[1]),
            max(0, int(box[2])),
            max(0, int(box[3])),
        ]
        for box in boxes
        if len(box) >= 4
    ]


def _find_overlapping_root_pairs(
    roots: List[int],
    eff_x1: np.ndarray,
    eff_y1: np.ndarray,
    eff_x2: np.ndarray,
    eff_y2: np.ndarray,
    eff_areas: np.ndarray,
    overlap_ratio: float,
    cross_line_overlap_frac: float = 0.7,
) -> List[Tuple[int, int]]:
    """현재 root bbox들 중 union 대상 pair를 벡터화로 찾는다."""
    if len(roots) < 2:
        return []

    root_idx = np.asarray(roots, dtype=np.int64)
    rx1 = eff_x1[root_idx]
    ry1 = eff_y1[root_idx]
    rx2 = eff_x2[root_idx]
    ry2 = eff_y2[root_idx]
    r_area = eff_areas[root_idx]

    inter_w = np.minimum(rx2[:, None], rx2[None, :]) - np.maximum(rx1[:, None], rx1[None, :])
    inter_h = np.minimum(ry2[:, None], ry2[None, :]) - np.maximum(ry1[:, None], ry1[None, :])
    valid = (inter_w > 0) & (inter_h > 0)

    smaller = np.minimum(r_area[:, None], r_area[None, :])
    ratio = np.zeros_like(inter_w, dtype=np.float64)
    np.divide(inter_w * inter_h, smaller, out=ratio, where=smaller > 0)

    # cross-line 가드: 세로 겹침(inter_h)이 두 박스 중 낮은 높이의 cross_line_overlap_frac
    rh = ry2 - ry1
    min_h = np.minimum(rh[:, None], rh[None, :])
    vertical_ok = inter_h >= cross_line_overlap_frac * min_h

    pair_positions = np.argwhere(np.triu(valid & (ratio >= overlap_ratio) & vertical_ok, k=1))
    return [
        (int(root_idx[i]), int(root_idx[j]))
        for i, j in pair_positions
    ]





