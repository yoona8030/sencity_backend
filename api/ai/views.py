# api/ai/views.py
from __future__ import annotations

import os
import re
import tempfile
import threading
from typing import Tuple

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

# EfficientNet 추론 코드 (수정하지 말 것)
from . import classifier_model_inference as cmi
# YOLOv5s 유틸
from .yolo_utils import yolo_predict_image_file, yolo_predict_file_obj


# -------------------------------------------------
# 전역 모델 싱글톤 (EfficientNet 분류기)
# -------------------------------------------------
_MODEL = None
_CLASS_NAMES: list[str] | None = None
_MODEL_LOCK = threading.Lock()

# 모델 파일 위치 (sencity_backend/efficientnet_models 폴더)
MODEL_PATH = os.path.join(
    settings.BASE_DIR,
    "efficientnet_models",
    "efficientnet_classifier_model.pth",
)


def get_model() -> Tuple[object, list[str]]:
    """
    EfficientNet 모델을 1번만 로드하여 캐싱.
    classifier_model_inference.load_model() 만 사용한다.
    """
    global _MODEL, _CLASS_NAMES

    with _MODEL_LOCK:
        if _MODEL is not None and _CLASS_NAMES is not None:
            return _MODEL, _CLASS_NAMES

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}")

        model, class_names = cmi.load_model(MODEL_PATH)
        _MODEL = model
        _CLASS_NAMES = list(class_names)
        return _MODEL, _CLASS_NAMES


def _normalize_label(raw: str) -> str:
    """
    '00_Goat', '07_Haron' 같은 체크포인트 라벨을
    프론트 aliasToKor 매핑에 쓰기 좋은 형태로 정규화한다.

    예:
      '00_Goat'        -> 'Goat'
      '01_Wild boar'   -> 'Wild boar'
      '07_Haron'       -> 'Heron'   # 오타 보정
    """
    if not raw:
        return raw

    label = str(raw)

    # 패턴 1: "00_Goat" -> "Goat"
    if "_" in label:
        left, right = label.split("_", 1)
        if left.isdigit():
            label = right

    # 패턴 2: 혹시 남아 있는 숫자 + 구분자 제거 (안전용)
    label = re.sub(r"^\d+[-_]*", "", label).strip()

    # 오타 보정: Haron -> Heron
    if label.lower() == "haron":
        label = "Heron"

    return label


# -------------------------------------------------
# 뷰들
# -------------------------------------------------
@method_decorator(csrf_exempt, name="dispatch")
class PingView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request, *args, **kwargs):
        return Response({"ok": True, "service": "ai", "env": bool(settings.DEBUG)})


@method_decorator(csrf_exempt, name="dispatch")
class ImageClassifyView(APIView):
    """
    POST /api/ai/classify/
    form-data:
        image: <파일>

    응답(프론트에서 기대하는 형태에 맞춤):

        {
          "ok": true,
          "results": [
            {
              "label": "Goat",       # CameraScreen 에서 쓰는 라벨 (정규화된)
              "label_raw": "00_Goat",# checkpoint 원본 라벨(디버깅용)
              "index": 0,            # class index
              "prob": 0.9234         # 0~1 스케일
            }
          ]
        }
    """
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, *args, **kwargs):
        # ─ 1) 파일 꺼내기 ────────────────────────────────
        image_file = request.FILES.get("image") or request.FILES.get("file")
        if not image_file:
            return Response(
                {"detail": "image 파일이 필요합니다. (form-data 로 image 필드 전송)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ─ 2) 모델 로드 ────────────────────────────────
        try:
            model, class_names = get_model()
        except FileNotFoundError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response(
                {"detail": f"모델 로드 중 오류: {e!s}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tmp = None
        tmp_path = None

        try:
            # ─ 3) 업로드 이미지를 임시 파일로 저장 ───────
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            for chunk in image_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
            tmp.close()

            # ─ 4) EfficientNet 추론 ────────────────────
            predicted_class, confidence = cmi.predict_image(
                tmp_path,
                model=model,
                class_names=class_names,
            )

            raw_label = str(predicted_class)
            norm_label = _normalize_label(raw_label)

            # class index 계산 (원본 라벨 기준)
            try:
                class_index = class_names.index(raw_label)
            except ValueError:
                class_index = -1

            # confidence (0~100) → 0~1 스케일
            score_unit = round(float(confidence) / 100.0, 4)

            # ─ 5) 응답 JSON (CameraScreen.pickTop 이 처리하기 좋은 형태) ─
            return Response(
                {
                    "ok": True,
                    "results": [
                        {
                            "label": norm_label,   # "Goat"
                            "label_raw": raw_label,
                            "index": class_index,
                            "prob": score_unit,
                        }
                    ],
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"detail": f"이미지 분류 중 오류: {e!s}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            if tmp is not None and tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


# -------------------------------------------------
# YOLOv5s - 실시간 프레임 분류
# -------------------------------------------------
@method_decorator(csrf_exempt, name="dispatch")
class YoloClassifyView(APIView):
    """
    POST /api/ai/classify-yolo/?min_conf=0.2

    - multipart/form-data 로 image 파일 업로드
    - min_conf 쿼리로 confidence threshold 조정 가능

    응답 예:
        {
          "label": "Goat" | null,
          "score": 0.78,
          "bbox": {
             "x1": ...,
             "y1": ...,
             "x2": ...,
             "y2": ...
          } | null
        }
    """
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        image_file = request.FILES.get("image")
        if not image_file:
            return Response(
                {"detail": "image 파일이 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 쿼리스트링으로 threshold 조절 (없으면 0.2)
        min_conf_str = request.GET.get("min_conf", None)
        try:
            min_conf = float(min_conf_str) if min_conf_str is not None else 0.20
        except ValueError:
            min_conf = 0.20

        # yolo_utils 에서 파일 객체 기반 추론 사용
        result = yolo_predict_file_obj(image_file, conf_threshold=min_conf)
        return Response(result, status=status.HTTP_200_OK)
