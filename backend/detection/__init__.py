"""검출 모듈. torch는 run_detection 호출 시 lazy 로드."""


def run_detection(img_bgr):
    from .detector import run_detection as _rd
    return _rd(img_bgr)
