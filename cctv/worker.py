# cctv/worker.py
import cv2, time, threading, logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection
from .models import Camera

log = logging.getLogger(__name__)

# === (더미) 모델 로더/추론: 나중에 네 모델로 교체 ===
def load_model():
    # TODO: TF/ONNX/PyTorch 로딩 코드
    return "DUMMY"

def predict(model, bgr_frame):
    # TODO: 전처리 → 모델 추론 → 라벨/확률 반환
    return ("멧돼지", 0.93, 5)  # (label, prob, animal_id)

# === 워커 ===
def worker_loop(camera_id: int, stream_url: str, fps: int = 2):
    ch = get_channel_layer()
    model = load_model()

    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        log.warning(f"[CCTV {camera_id}] open 실패. 재시도 중...")
        while True:
            cap.open(stream_url)
            if cap.isOpened(): break
            time.sleep(2)

    interval = 1.0 / max(1, fps)

    while True:
        ok, frame = cap.read()
        if not ok:
            log.warning(f"[CCTV {camera_id}] frame read 실패. 재연결...")
            cap.release()
            time.sleep(1)
            cap = cv2.VideoCapture(stream_url)
            continue

        label, prob, animal_id = predict(model, frame)

        data = {
            "cameraId": camera_id,
            "label": label,
            "prob": round(float(prob), 4),
            "animal_id": animal_id,
            "ts": time.time(),
        }
        async_to_sync(ch.group_send)(
            f"cctv_{camera_id}",
            {"type": "prediction", "data": data}
        )

        time.sleep(interval)

def start_all_workers():
    # 포크/스레드에서 DB 커넥션 충돌 방지
    if connection.connection:
        connection.close()

    cams = list(Camera.objects.filter(is_active=True).values("id", "stream_url"))
    if not cams:
        log.warning("활성 카메라가 없습니다. admin에서 Camera 추가하세요.")
    for cam in cams:
        t = threading.Thread(
            target=worker_loop,
            args=(cam["id"], cam["stream_url"], 2),  # fps=2 예시
            daemon=True,
        )
        t.start()
        log.info(f"[CCTV {cam['id']}] 워커 시작")
