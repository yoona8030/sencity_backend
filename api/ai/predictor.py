# api/ai/predictor.py
import os
import re
import numpy as np
import tensorflow as tf
from keras.layers import TFSMLayer  # Keras 3에서 SavedModel 로드용

# ─────────────────────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
MODEL_DIR = os.path.join(BASE_DIR, "converted_savedmodel", "model.savedmodel")
LABEL_PATH = os.path.join(BASE_DIR, "converted_savedmodel", "labels.txt")

# ─────────────────────────────────────────────────────────────
# 라벨 파서: "0 water dear01" → "water dear"
#   1) 맨 앞 정수 인덱스 제거
#   2) 끝쪽 연속 숫자 꼬리 제거(01, 02 ...)
#   3) 트리밍
# ─────────────────────────────────────────────────────────────
def _parse_label_line(line: str) -> str:
    s = line.strip()
    if not s:
        return s
    parts = s.split()
    # 앞 토큰이 정수면 제거
    if parts and re.fullmatch(r"\d+", parts[0]):
        parts = parts[1:]
    clean = " ".join(parts)
    # 끝자리 숫자 꼬리 제거 (예: dear01 -> dear)
    clean = re.sub(r"\d+$", "", clean).strip()
    # 폴백: 비면 원문 유지
    return clean if clean else s

def _load_labels(path: str) -> list[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"labels file not found: {path}")
    labels: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            labels.append(_parse_label_line(raw))
    if not labels:
        raise ValueError(f"no labels parsed from: {path}")
    return labels


class _Predictor:
    def __init__(self):
        # SavedModel을 추론 전용 레이어로 로드
        # (사전에 python -c로 확인한 signature: 'serving_default')
        self.model = TFSMLayer(MODEL_DIR, call_endpoint="serving_default")

        # 라벨 로드 (받은 형식에 맞춰 파싱)
        self.labels = _load_labels(LABEL_PATH)
        self.num_classes = len(self.labels)

        # 워밍업 호출 (입력 크기가 다르면 target 변경)
        _ = self.model(tf.zeros([1, 224, 224, 3], dtype=tf.float32), training=False)

    # ─────────────────────────────────────────────────────────
    # 전처리: bytes -> float32[1,H,W,3] (0~1), 리사이즈
    # ─────────────────────────────────────────────────────────
    def _preprocess(self, img_bytes, target=(224, 224)):
        img = tf.io.decode_image(img_bytes, channels=3, expand_animations=False)
        img = tf.image.convert_image_dtype(img, tf.float32)   # [0,1]
        img = tf.image.resize(img, target)
        return tf.expand_dims(img, 0)  # [1,H,W,3]

    # ─────────────────────────────────────────────────────────
    # 다양한 출력 형태(dict/list/tensor)를 1D numpy로 정규화
    # ─────────────────────────────────────────────────────────
    def _to_numpy_1d(self, outputs):
        if isinstance(outputs, dict):
            outputs = next(iter(outputs.values()))
        if isinstance(outputs, (list, tuple)):
            outputs = outputs[0]
        arr = outputs.numpy() if hasattr(outputs, "numpy") else np.asarray(outputs)
        if arr.ndim == 2 and arr.shape[0] == 1:
            arr = arr[0]
        return arr

    # ─────────────────────────────────────────────────────────
    # 예측
    #  - 모델 출력이 확률 합 1이 아니면 softmax 적용
    #  - labels 개수와 출력 차원수가 다르면 안전하게 min에 맞춰 자름
    # ─────────────────────────────────────────────────────────
    def predict(self, img_bytes, topk=3):
        x = self._preprocess(img_bytes, target=(224, 224))
        raw = self.model(x, training=False)
        logits_or_probs = self._to_numpy_1d(raw)

        probs = logits_or_probs
        s = float(np.sum(probs))
        if not (0.99 <= s <= 1.01):
            probs = tf.nn.softmax(probs).numpy()

        # 출력 차원과 라벨 수가 불일치할 수 있으니 방어 코드
        C = min(len(probs), self.num_classes)
        probs = probs[:C]
        labels = self.labels[:C]

        idx = np.argsort(probs)[-min(topk, C):][::-1]
        return [
            {
                "label": labels[i] if i < len(labels) else f"class_{i}",
                "index": int(i),
                "prob": float(probs[i]),
            }
            for i in idx
        ]


# 싱글톤
predictor = _Predictor()
