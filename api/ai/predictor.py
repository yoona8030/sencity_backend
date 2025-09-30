# api/ai/predictor.py
import os, re, json
import numpy as np
import tensorflow as tf

# --- Keras/TensorFlow 호환 임포트 가드 ---
try:
    # Keras 3 (권장)
    from keras.layers import TFSMLayer  # type: ignore[reportMissingImports]
    from keras import models as keras_models # type: ignore[reportMissingImports]
    from keras.applications.efficientnet import preprocess_input as effnet_preprocess # type: ignore[reportMissingImports]
    _KERAS_FLAVOR = "keras3"
except Exception:
    # TF-Keras 대체 (TFSMLayer는 없음)
    TFSMLayer = None
    from tensorflow.keras import models as keras_models # type: ignore[reportMissingImports]
    from tensorflow.keras.applications.efficientnet import preprocess_input as effnet_preprocess # type: ignore[reportMissingImports]
    _KERAS_FLAVOR = "tf.keras"

# ─────────────────────────────────────────────────────────────
# 경로 설정 (새 모델 산출물 경로)
# ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # ...\sencity_backend
MODEL_ROOT     = os.path.join(BASE_DIR, "sencity_classification_model", "models")
SAVEDMODEL_DIR = os.path.join(MODEL_ROOT, "animal_classifier_savedmodel")
KERAS_PATH     = os.path.join(MODEL_ROOT, "animal_classifier.keras")
LABEL_PATH     = os.path.join(MODEL_ROOT, "labels.txt")
CLASS_INFO_JSON= os.path.join(MODEL_ROOT, "class_info.json")

# ─────────────────────────────────────────────────────────────
# 라벨 파서: "0 goat01" → "goat"
# ─────────────────────────────────────────────────────────────
def _parse_label_line(line: str) -> str:
    s = line.strip()
    if not s:
        return s
    parts = s.split()
    if parts and re.fullmatch(r"\d+", parts[0]):
        parts = parts[1:]
    clean = " ".join(parts)
    clean = re.sub(r"\d+$", "", clean).strip()
    return clean if clean else s

def _load_labels(path: str) -> list[str]:
    # 1) labels.txt 우선
    if os.path.exists(path):
        labels: list[str] = []
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    labels.append(_parse_label_line(raw))
        if labels:
            return labels

    # 2) class_info.json에서 복구
    if os.path.exists(CLASS_INFO_JSON):
        data = json.load(open(CLASS_INFO_JSON, encoding="utf-8"))
        classes = data.get("class_names")
        if classes:
            with open(LABEL_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(classes))
            return [_parse_label_line(c) for c in classes]

    # 3) 마지막 폴백: 모델 출력 차원 사용
    try:
        if os.path.exists(KERAS_PATH):
            m = keras_models.load_model(KERAS_PATH)
            n = m.output_shape[-1]
            return [f"class_{i}" for i in range(n)]
    except Exception:
        pass
    raise FileNotFoundError("라벨 정보를 찾을 수 없습니다. labels.txt 또는 class_info.json을 준비하세요.")

class _Predictor:
    def __init__(self):
        # --- 모델 로드: .keras 우선, 없으면 SavedModel ---
        if os.path.exists(KERAS_PATH):
            self.model = keras_models.load_model(KERAS_PATH)
        elif os.path.exists(SAVEDMODEL_DIR):
            if TFSMLayer is not None:
                self.model = TFSMLayer(SAVEDMODEL_DIR, call_endpoint="serving_default")
            else:
                # TF-Keras 환경: SavedModel을 직접 로드(서명 처리 필요 시 별도 핸들링)
                self.model = tf.saved_model.load(SAVEDMODEL_DIR)
        else:
            raise FileNotFoundError(f"Model not found: {KERAS_PATH} or {SAVEDMODEL_DIR}")

        self.labels = _load_labels(LABEL_PATH)
        self.num_classes = len(self.labels)

        # 워밍업 (가능할 때만 호출)
        try:
            _ = self.model(tf.zeros([1, 224, 224, 3], dtype=tf.float32), training=False)
        except Exception:
            pass

    def _preprocess(self, img_bytes, target=(224, 224)):
        img = tf.io.decode_image(img_bytes, channels=3, expand_animations=False)  # uint8 [0..255]
        img = tf.image.resize(img, target)
        img = tf.cast(img, tf.float32)
        # resize 결과가 0~1 범위일 수 있어 255 보정
        img = tf.where(img <= 1.0, img * 255.0, img)
        img = effnet_preprocess(img)  # 학습과 동일 전처리
        return tf.expand_dims(img, 0)  # [1,H,W,3]

    def _to_numpy_1d(self, outputs):
        if isinstance(outputs, dict):
            outputs = next(iter(outputs.values()))
        if isinstance(outputs, (list, tuple)):
            outputs = outputs[0]
        arr = outputs.numpy() if hasattr(outputs, "numpy") else np.asarray(outputs)
        if arr.ndim == 2 and arr.shape[0] == 1:
            arr = arr[0]
        return arr

    def predict(self, img_bytes, topk=3):
        x = self._preprocess(img_bytes, target=(224, 224))
        raw = self.model(x, training=False) if callable(getattr(self.model, "__call__", None)) else self.model(x)
        logits_or_probs = self._to_numpy_1d(raw)

        probs = logits_or_probs
        s = float(np.sum(probs))
        if not (0.99 <= s <= 1.01):
            probs = tf.nn.softmax(probs).numpy()

        C = min(len(probs), self.num_classes)
        probs = probs[:C]; labels = self.labels[:C]
        idx = np.argsort(probs)[-min(topk, C):][::-1]
        return [{"label": labels[i] if i < len(labels) else f"class_{i}",
                 "index": int(i), "prob": float(probs[i])} for i in idx]

# 싱글톤
predictor = _Predictor()
