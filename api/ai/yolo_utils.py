# api/ai/yolo_utils
import pathlib
from typing import Dict, Any

import torch
from PIL import Image, UnidentifiedImageError
from django.conf import settings

# settings.py 에서 경로 가져옴
MODEL_PATH = settings.YOLO_MODEL_PATH

_yolo_model = None


def get_yolo_model():
    """
    YOLO 모델을 전역 1회 로드.
    (.pt 안에 PosixPath 가 들어있을 때 Windows 에서 깨지는 문제 우회)
    """
    global _yolo_model
    if _yolo_model is None:
        orig_posix = pathlib.PosixPath
        try:
            pathlib.PosixPath = pathlib.WindowsPath

            print("[YOLO] MODEL_PATH:", MODEL_PATH)

            _yolo_model = torch.hub.load(
                "ultralytics/yolov5",
                "custom",
                path=MODEL_PATH,
                source="github",
                trust_repo=True,
            )
            _yolo_model.eval()

            print("[YOLO] model.names:", _yolo_model.names)
            print("[YOLO] num classes:", len(_yolo_model.names))
        finally:
            pathlib.PosixPath = orig_posix

    return _yolo_model


def _select_best_prediction(pred, results, conf_threshold: float) -> Dict[str, Any] | None:
    """
    - conf_threshold 보다 낮은 박스는 버리고
    - 남은 것 중 confidence 가 가장 높은 1개만 선택
    """
    if pred is None or pred.shape[0] == 0:
        return None

    # pred: [x1, y1, x2, y2, conf, cls]
    pred = pred[pred[:, 4] >= conf_threshold]

    if pred.shape[0] == 0:
        return None

    # confidence 내림차순 정렬 후 첫 번째 박스 사용
    pred = pred[pred[:, 4].argsort(descending=True)]
    best = pred[0]

    x1, y1, x2, y2, conf, cls = best.tolist()
    label = results.names[int(cls)]

    return {
        "label": label,
        "score": float(round(conf, 4)),
        "bbox": {
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),
        },
    }


def yolo_predict_image_file(image_path: str, conf_threshold: float = 0.20) -> Dict[str, Any]:
    """
    이미지 경로를 받아 YOLO로 추론.
    conf_threshold 이상인 박스 중 confidence 가 가장 높은 1개만 반환.
    """
    model = get_yolo_model()

    try:
        results = model(image_path)
    except Exception as e:
        print("[YOLO][ERROR] failed to open image:", image_path, "->", e)
        return {"label": None, "score": 0.0, "bbox": None}

    pred = results.xyxy[0]
    best = _select_best_prediction(pred, results, conf_threshold)

    if best is None:
        return {"label": None, "score": 0.0, "bbox": None}
    return best


def yolo_predict_file_obj(file_obj, conf_threshold: float = 0.20) -> Dict[str, Any]:
    """
    file-like object (예: request.FILES['image']) 로 추론.
    """
    model = get_yolo_model()

    try:
        image = Image.open(file_obj).convert("RGB")
    except UnidentifiedImageError:
        print("[YOLO][ERROR] invalid image data")
        return {"label": None, "score": 0.0, "bbox": None}

    results = model(image)
    pred = results.xyxy[0]
    best = _select_best_prediction(pred, results, conf_threshold)

    if best is None:
        return {"label": None, "score": 0.0, "bbox": None}
    return best
