# dashboard/views_ai.py
# -*- coding: utf-8 -*-
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings
import threading, json, re, os

from .ai_worker import StreamWorker, YoloInfer

AI_LOCK = threading.Lock()
AI_CTX = {
    "model": None,
    "stream": None,
    "infer": None,
    "running": False,
    "conf": 0.15,
    "src": "",
}

# 모델 경로 후보 (환경에 맞게 필요시 조정)
MODEL_CANDIDATES = [
    r"animal_model.pt",
    os.path.join(os.getcwd(), "animal_model.pt"),
    os.path.join(os.getcwd(), "media", "models", "animal_model.pt"),
    os.path.join(os.path.dirname(os.getcwd()), "animal_model.pt"),
    r"C:\Users\a9349\sencity_backend\animal_model.pt",
]

def _find_model_path():
    for p in MODEL_CANDIDATES:
        if os.path.exists(p): return p
    raise FileNotFoundError("animal_model.pt 파일을 찾지 못했습니다.")

def _load_model_if_needed():
    if AI_CTX["model"] is not None: return AI_CTX["model"]
    import torch
    model_path = _find_model_path()
    # 로컬 커스텀 모델 로드 (yolov5)
    m = torch.hub.load('ultralytics/yolov5', 'custom', path=model_path, trust_repo=True)
    # 기본 하이퍼파라미터
    m.conf = 0.15
    m.iou  = 0.50
    m.max_det = 300
    AI_CTX["model"] = m
    return m

@require_POST
def ai_start(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        body = {}
    src_raw = str(body.get("stream_url", "")).strip()
    conf = float(body.get("confidence", 0.15))

    # 입력 검증
    if not src_raw or not re.match(r"^https?://", src_raw, re.I):
        return JsonResponse({"success": False, "error": "invalid source"}, status=400)
    if src_raw.lower().endswith(".mp4"):
        return JsonResponse({"success": False, "error": "mp4 not supported"}, status=400)

    # 모델 로드
    try:
        _load_model_if_needed()
    except Exception as e:
        return JsonResponse({"success": False, "error": f"model load error: {e}"}, status=500)

    # 기존 세션 정리
    with AI_LOCK:
        if AI_CTX.get("infer"):
            try: AI_CTX["infer"].stop()
            except: pass
        if AI_CTX.get("stream"):
            try: AI_CTX["stream"].stop()
            except: pass
        AI_CTX.update({"infer": None, "stream": None, "running": False})

    # 백그라운드 시작 (응답은 즉시 성공 반환)
    stream = StreamWorker(src_raw, snapshot_fallback=True, snapshot_interval_ms=350)  # ≈2.8fps
    infer  = YoloInfer(stream, AI_CTX["model"], conf_thres=conf)
    stream.start(); infer.start()

    with AI_LOCK:
        AI_CTX.update({
            "stream": stream,
            "infer":  infer,
            "running": True,
            "conf": conf,
            "src": src_raw,
        })
    return JsonResponse({"success": True})

@require_GET
def ai_status(request):
    with AI_LOCK:
        infer = AI_CTX.get("infer")
        stream = AI_CTX.get("stream")
        running = AI_CTX.get("running", False)
        frame_b64 = infer.last_jpeg_base64 if infer else None
        dets = infer.detections if infer else []
        total = infer.total_animals if infer else 0
        stream_error = getattr(stream, "err", None) if stream else None
    return JsonResponse({
        "is_running": bool(running),
        "frame": frame_b64,
        "detections": dets,
        "total_animals": total,
        "stream_error": stream_error,
        "src": AI_CTX.get("src"),
        "conf": AI_CTX.get("conf"),
    })

@require_POST
def ai_stop(request):
    with AI_LOCK:
        if AI_CTX.get("infer"):
            try: AI_CTX["infer"].stop()
            except: pass
        if AI_CTX.get("stream"):
            try: AI_CTX["stream"].stop()
            except: pass
        AI_CTX.update({"infer": None, "stream": None, "running": False})
    return JsonResponse({"success": True})
