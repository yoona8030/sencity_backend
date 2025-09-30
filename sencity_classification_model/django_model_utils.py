# sencity_classification_model/django_model_utils.py
# Django에서 분류모델 사용 유틸 (SavedModel 우선, .keras/.h5도 백업 경로)

import os
import io
import json
import numpy as np
from PIL import Image

import tensorflow as tf
from tensorflow import keras

# 전역 분류기 인스턴스 (앱 시작 시 1회 로드 후 재사용)
animal_classifier = None


class AnimalClassifier:
    """
    Django 서버에서 사용할 동물 분류기 클래스
    - SavedModel 폴더/단일 모델 파일(.keras/.h5) 로드 지원
    - 업로드 파일/파일 경로 기반 예측 지원
    """

    def __init__(self, model_path: str, class_info_path: str):
        """
        Args:
            model_path: SavedModel 폴더 경로 또는 단일 모델 파일 경로(.keras/.h5)
            class_info_path: 클래스 정보 JSON 파일 경로
        """
        self.model = None
        self._saved_model_fn = None
        self.class_names = []
        self.img_size = 224
        self.num_classes = 10

        self.load_model(model_path)
        self.load_class_info(class_info_path)

    def load_model(self, model_path: str):
        """
        저장된 모델을 로드함.
        - 디렉터리면 SavedModel로 가정
        - 파일이면 .keras / .h5 모두 시도 (Keras 3에서는 .keras 권장)
        """
        try:
          if os.path.isdir(model_path):
              # ✅ SavedModel (model.export(...) 로 만든 형태)
              loaded = tf.saved_model.load(model_path)
              fn = loaded.signatures.get("serving_default")
              if fn is None:
                  raise RuntimeError("SavedModel에 'serving_default' 시그니처가 없습니다.")
              self._saved_model_fn = fn
              self.model = None
              print(f"[AnimalClassifier] SavedModel 로드 성공: {model_path}")
          else:
              # ✅ 단일 파일(.keras 권장 / .h5는 최후의 수단)
              self.model = keras.models.load_model(model_path, compile=False)
              self._saved_model_fn = None
              print(f"[AnimalClassifier] Keras 모델 로드 성공: {model_path}")
        except Exception as e:
            raise Exception(f"모델 로드 실패: {e}")

    def load_class_info(self, class_info_path: str):
        """
        클래스 정보를 JSON 파일에서 로드함.
        JSON 스키마 예:
        {
          "class_names": [...],
          "num_classes": 10,
          "input_size": 224
        }
        """
        try:
            with open(class_info_path, "r", encoding="utf-8") as f:
                class_info = json.load(f)
            self.class_names = class_info.get("class_names", [])
            self.num_classes = int(class_info.get("num_classes", len(self.class_names)))
            self.img_size = int(class_info.get("input_size", 224))

            if not self.class_names:
                raise ValueError("class_info.json에 'class_names'가 비어있습니다.")

            print(
                f"[AnimalClassifier] 클래스 정보 로드: {len(self.class_names)}개, "
                f"입력크기={self.img_size}, 클래스수={self.num_classes}"
            )
        except Exception as e:
            raise Exception(f"클래스 정보 로드 실패: {e}")

    def preprocess_image(self, image_data, is_file_path: bool = False):
        """
        이미지를 모델 입력 형태로 전처리함.

        Args:
            image_data: 이미지 파일 경로(str) 또는 바이트 데이터(bytes)
            is_file_path: image_data가 파일 경로인지 여부

        Returns:
            (1, H, W, 3) float32 [0,1] 범위 배열
        """
        try:
            if is_file_path:
                img = Image.open(image_data)
            else:
                img = Image.open(io.BytesIO(image_data))

            if img.mode != "RGB":
                img = img.convert("RGB")

            img = img.resize((self.img_size, self.img_size))
            img_array = np.array(img, dtype=np.float32)
            img_array = np.expand_dims(img_array, axis=0)  # 배치 차원
            img_array /= 255.0  # 정규화

            return img_array
        except Exception as e:
            raise Exception(f"이미지 전처리 실패: {e}")

    def predict(self, image_data, is_file_path: bool = False, top_k: int = 3):
        """
        이미지에 대해 동물 종을 예측함.

        Args:
            image_data: 파일 경로(str) 또는 바이트(bytes)
            is_file_path: 경로 여부
            top_k: 상위 k개 결과 반환

        Returns:
            dict: 예측 결과
        """
        try:
            # 전처리
            img_array = self.preprocess_image(image_data, is_file_path=is_file_path)

            # 예측
            if self._saved_model_fn is not None:
              # ✅ SavedModel: Tensor 입력 → dict 출력
              inputs = tf.convert_to_tensor(img_array, dtype=tf.float32)
              out = self._saved_model_fn(inputs)
              # 출력 키가 환경에 따라 다를 수 있으니 첫 키 사용
              first_key = next(iter(out.keys()))
              probs = out[first_key].numpy()[0]
            else:
                # ✅ Keras 모델: predict 사용
                preds = self.model.predict(img_array, verbose=0)
                probs = preds[0]

            # 상위 k 추출
            top_k = max(1, min(top_k, len(self.class_names)))
            top_indices = np.argsort(probs)[-top_k:][::-1]

            top_predictions = [
                {
                    "class_name": self.class_names[idx],
                    "confidence": float(probs[idx]),
                    "confidence_percent": round(float(probs[idx]) * 100.0, 2),
                }
                for idx in top_indices
            ]

            all_predictions = {
                self.class_names[i]: {
                    "confidence": float(probs[i]),
                    "confidence_percent": round(float(probs[i]) * 100.0, 2),
                }
                for i in range(len(self.class_names))
            }

            return {
                "success": True,
                "predicted_class": top_predictions[0]["class_name"],
                "confidence": top_predictions[0]["confidence"],
                "confidence_percent": top_predictions[0]["confidence_percent"],
                "top_predictions": top_predictions,
                "all_predictions": all_predictions,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_model_info(self):
        """
        모델 정보를 반환.
        """
        return {
            "class_names": self.class_names,
            "num_classes": self.num_classes,
            "input_size": self.img_size,
            "model_loaded": self.model is not None,
        }


# ---------- Django에서 직접 호출할 함수들 ----------

def initialize_classifier(model_dir: str):
    """
    분류기를 초기화하고 전역 변수에 보관.
    Django 앱 초기화 시 1회 호출 권장.

    Args:
        model_dir: 모델 파일들이 존재하는 디렉터리
                   (예: .../sencity_classification_model/models)
                   내부에 아래가 있는지 확인:
                   - animal_classifier_savedmodel/   (✅ 권장)
                   - animal_classifier.keras         (선택)
                   - animal_classifier.h5            (최후의 수단)
                   - class_info.json                 (필수)
    """
    savedmodel_dir = os.path.join(model_dir, "animal_classifier_savedmodel")
    keras_file = os.path.join(model_dir, "animal_classifier.keras")
    h5_file = os.path.join(model_dir, "animal_classifier.h5")
    class_info_path = os.path.join(model_dir, "class_info.json")

    if not os.path.exists(class_info_path):
        raise FileNotFoundError(f"class_info.json을 찾을 수 없습니다: {class_info_path}")

    # ✅ 우선순위: SavedModel 폴더 > .keras > .h5
    if os.path.isdir(savedmodel_dir):
        model_path = savedmodel_dir
    elif os.path.exists(keras_file):
        model_path = keras_file
    else:
        model_path = h5_file  # (Keras3와 호환 이슈 가능)

    global animal_classifier
    animal_classifier = AnimalClassifier(model_path, class_info_path)
    return animal_classifier


def predict_uploaded_image(uploaded_file, top_k: int = 3):
    """
    Django 업로드 파일 객체(UploadedFile)에 대해 예측 수행.
    """
    try:
        if animal_classifier is None:
            raise RuntimeError("animal_classifier가 초기화되지 않았습니다. initialize_classifier()를 먼저 호출하세요.")
        image_bytes = uploaded_file.read()
        return animal_classifier.predict(image_bytes, is_file_path=False, top_k=top_k)
    except Exception as e:
        return {"success": False, "error": f"예측 중 오류 발생: {str(e)}"}


def predict_image_path(image_path: str, top_k: int = 3):
    """
    서버에 저장된 이미지 경로로 예측 수행.
    """
    try:
        if animal_classifier is None:
            raise RuntimeError("animal_classifier가 초기화되지 않았습니다. initialize_classifier()를 먼저 호출하세요.")
        if not os.path.exists(image_path):
            return {"success": False, "error": f"파일을 찾을 수 없습니다: {image_path}"}
        return animal_classifier.predict(image_path, is_file_path=True, top_k=top_k)
    except Exception as e:
        return {"success": False, "error": f"예측 중 오류 발생: {str(e)}"}

