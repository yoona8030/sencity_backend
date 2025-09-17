# api/ml.py
from __future__ import annotations
import os, sys
from typing import List, Dict
from PIL import Image

try:
    import numpy as np
    import tensorflow as tf
    TF_AVAILABLE = True
except Exception:
    TF_AVAILABLE = False

# ── 경로: 프로젝트 루트의 converted_savedmodel 사용
MODEL_DIR  = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "converted_savedmodel"))
MODEL_PATH = os.path.join(MODEL_DIR, "model.savedmodel")

# 라벨 파일: labels.txt 또는 labels 둘 다 허용
LABELS_PATH_TXT = os.path.join(MODEL_DIR, "labels.txt")
LABELS_PATH_RAW = os.path.join(MODEL_DIR, "labels")
LABELS_PATH = LABELS_PATH_TXT if os.path.exists(LABELS_PATH_TXT) else LABELS_PATH_RAW

_model = None
_labels: List[str] | None = None

def _predict_probs(img: Image.Image):
    """
    전체 클래스 확률 벡터와 라벨 리스트를 반환: (labels, probs[np.ndarray shape=(C,)])
    기존 predict_topk 내부 로직을 재사용.
    """
    labels = _load_labels()
    model  = _load_model()

    # 모델이 없으면 더미 분포
    if not (TF_AVAILABLE and model is not None):
        name_hint = (getattr(img, "filename", "") or "").lower()
        dir_hint  = os.path.basename(os.path.dirname(name_hint)).lower()
        base = [0.2] * len(labels)
        for i, lb in enumerate(labels):
            if lb.lower() in name_hint or lb.lower() in dir_hint:
                base[i] += 0.6
        s = sum(base) or 1.0
        import numpy as np
        return labels, np.asarray([v/s for v in base], dtype=float)

    # --- 모델 추론 (predict_topk와 동일한 경로) ---
    x = _preprocess(img)
    fn = getattr(model, "signatures", {}).get("serving_default")
    if fn is not None:
        y = fn(tf.constant(x))
        if isinstance(y, dict):
            prefer_keys = ["probabilities", "softmax", "predictions", "logits", "sequential_3"]
            out = None
            for kname in prefer_keys:
                if kname in y:
                    out = y[kname]
                    break
            if out is None:
                out = next(iter(y.values()))
        else:
            out = y
    else:
        out = model(x)

    import numpy as np
    arr = out.numpy() if hasattr(out, "numpy") else np.asarray(out)
    if arr.ndim == 2:
        arr = arr[0]
    elif arr.ndim > 2:
        arr = arr.reshape((arr.shape[0], -1))[0]

    # 확률 아니면 softmax
    try:
        needs_softmax = abs(float(arr.sum()) - 1.0) > 1e-3
    except Exception:
        needs_softmax = True
    if needs_softmax:
        arr = tf.nn.softmax(arr, axis=-1).numpy()

    # 라벨 길이 보정
    n_cls = int(arr.shape[-1])
    if len(labels) < n_cls:
        labels = labels + [str(i) for i in range(len(labels), n_cls)]
    elif len(labels) > n_cls:
        labels = labels[:n_cls]

    return labels, arr


# --- “고라니/노루”, “중대백로/왜가리”, “다람쥐/청설모”를 묶는 그룹 TopK ---
GROUP_MAP = {
    # 사슴류: water deer(고라니), roe deer(노루)
    "water deer": "deer",
    "roe deer":   "deer",

    # 백로/왜가리 계열
    "egret": "heron_egret",
    "heron": "heron_egret",

    # 다람쥐과: squirrel(청설모), chipmunk(멧다람쥐)
    "squirrel":  "sciuridae",
    "chipmunk":  "sciuridae",
    # 필요 시 오탈자 보정
    "water dear": "deer",  # 오타 라벨 대비
}

# 그룹의 한글 표시(응답용)
GROUP_DISPLAY_KO = {
    "deer":        "고라니/노루",
    "heron_egret": "왜가리/중대백로",
    "sciuridae":   "다람쥐/청설모",
}

def predict_topk_grouped(img: Image.Image, k: int = 3):
    """
    원시 클래스 확률을 그룹 키로 합산 → 정규화 → 그룹 TopK 반환.
    반환 예: [{'group': 'deer', 'label_ko': '고라니/노루', 'prob': 0.83, 'members': [('water deer', 0.7), ('roe deer', 0.13)]}, ...]
    """
    import numpy as np
    labels, probs = _predict_probs(img)

    # 1) 그룹 합산
    group_scores = {}           # group_key -> float
    group_members = {}          # group_key -> list[(label, prob)]
    for lb, p in zip(labels, probs):
        g = GROUP_MAP.get(lb.lower(), lb.lower())  # 매핑 없으면 자기 자신을 그룹 키로 (단일 종)
        group_scores[g] = group_scores.get(g, 0.0) + float(p)
        group_members.setdefault(g, []).append((lb, float(p)))

    # 2) 정규화(합=1)
    total = sum(group_scores.values()) or 1.0
    for g in list(group_scores.keys()):
        group_scores[g] /= total

    # 3) 정렬 & TopK
    order = sorted(group_scores.items(), key=lambda x: -x[1])[:k]

    # 4) 반환 구조
    out = []
    for g, score in order:
        members_sorted = sorted(group_members[g], key=lambda x: -x[1])
        out.append({
            "group": g,
            "label_ko": GROUP_DISPLAY_KO.get(g),  # 단일종이면 None
            "prob": score,
            "members": members_sorted,
        })
    return out


# ── 라벨 한 줄 정규화(주석/앞번호/뒤꼬리 숫자 제거)
def _normalize_label(s: str) -> str:
    s = (s or "").strip()
    if not s or s.startswith("#"):
        return ""
    parts = s.split()
    if parts and parts[0].isdigit():   # "0 roe deer07" → "roe deer07"
        parts = parts[1:]
    s = " ".join(parts)
    s = s.rstrip("0123456789")         # "roe deer07" → "roe deer"
    s = s.replace("_", " ").strip()
    return s

def _load_labels() -> List[str]:
    global _labels
    if _labels is not None:
        return _labels
    labels: List[str] = []
    try:
        with open(LABELS_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                z = _normalize_label(ln)
                if z:
                    labels.append(z)
        print("[ml] labels loaded(normalized):", labels, file=sys.stderr)
    except FileNotFoundError:
        labels = ["고라니", "멧토끼", "너구리", "고양이", "멧돼지"]
        print("[ml] labels fallback:", labels, file=sys.stderr)
    _labels = labels
    return labels

def _load_model():
    global _model
    if _model is not None:
        return _model
    print("[ml] TF_AVAILABLE:", TF_AVAILABLE, file=sys.stderr)
    print("[ml] MODEL_DIR:", MODEL_DIR, file=sys.stderr)
    print("[ml] MODEL_PATH exists:", os.path.exists(MODEL_PATH), MODEL_PATH, file=sys.stderr)
    if TF_AVAILABLE and os.path.exists(MODEL_PATH):
        _model = tf.saved_model.load(MODEL_PATH)
        print("[ml] model loaded", file=sys.stderr)
        if hasattr(_model, "signatures"):
            print("[ml] signatures:", list(_model.signatures.keys()), file=sys.stderr)
            fn = _model.signatures.get("serving_default")
            if fn:
                print("[ml] outputs:", fn.structured_outputs, file=sys.stderr)
    else:
        _model = None
        print("[ml] using DUMMY (no TF or no model)", file=sys.stderr)
    return _model

def _preprocess(img: Image.Image, size=(224, 224)):
    if not TF_AVAILABLE:
        return None
    arr = img.convert("RGB").resize(size)
    arr = np.asarray(arr, dtype=np.float32) / 255.0
    return arr[None, ...]  # (1,H,W,3)

def predict_topk(img: Image.Image, k: int = 3) -> List[Dict]:
    labels = _load_labels()
    model  = _load_model()

    if TF_AVAILABLE and model is not None:
        x = _preprocess(img)
        fn = getattr(model, "signatures", {}).get("serving_default")
        if fn is not None:
            y = fn(tf.constant(x))
            if isinstance(y, dict):
                # ⚠️ Tensor에 대해 파이썬 truthiness 금지 → "키 존재"만 확인
                prefer_keys = ["probabilities", "softmax", "predictions", "logits", "sequential_3"]
                out = None
                for kname in prefer_keys:
                    if kname in y:          # ← 존재만 확인
                        out = y[kname]
                        break
                if out is None:
                    # 아무 키도 못 찾으면 첫 값 사용
                    out = next(iter(y.values()))
            else:
                out = y
        else:
            out = model(x)

        # --- 텐서를 ndarray로 변환
        arr = out.numpy() if hasattr(out, "numpy") else np.asarray(out)
        if arr.ndim == 2:
            arr = arr[0]
        elif arr.ndim > 2:
            arr = arr.reshape((arr.shape[0], -1))[0]

        # --- 확률 아니면 softmax
        try:
            needs_softmax = abs(float(arr.sum()) - 1.0) > 1e-3
        except Exception:
            needs_softmax = True
        if needs_softmax:
            arr = tf.nn.softmax(arr, axis=-1).numpy()

        # --- 라벨 길이 보정
        n_cls = int(arr.shape[-1])
        if len(labels) < n_cls:
            labels = labels + [str(i) for i in range(len(labels), n_cls)]
        elif len(labels) > n_cls:
            labels = labels[:n_cls]

        idxs = np.argsort(-arr)[:k]
        return [{"label": labels[i], "prob": float(arr[i])} for i in idxs]

    # ── 더미 경로(모델 없음) : 파일명/폴더명 힌트로 가중
    name_hint = (getattr(img, "filename", "") or "").lower()
    dir_hint  = os.path.basename(os.path.dirname(name_hint)).lower()
    base = [0.2] * len(labels)
    for i, lb in enumerate(labels):
        if lb.lower() in name_hint or lb.lower() in dir_hint:
            base[i] += 0.6
    s = sum(base) or 1.0
    probs = [v / s for v in base]
    pairs = list(zip(labels, probs))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [{"label": lb, "prob": float(p)} for lb, p in pairs[:k]]
