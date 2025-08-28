from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import cv2

from .models import CCTVDevice, MotionSensor
from dashboard.vision.adapter import SingletonClassifier


# 대시보드 홈 화면
def dashboard_home(request):
    # 더미 데이터
    devices = [
        type('D', (), {'name': 'CCTV 1', 'status': 'ONLINE'})(),
        type('D', (), {'name': 'CCTV 2', 'status': 'OFFLINE'})(),
        type('D', (), {'name': 'CCTV 3', 'status': 'OFFLINE'})(),
        type('D', (), {'name': 'CCTV 4', 'status': 'OFFLINE'})(),
    ]
    sensors = [
        type('S', (), {'device': devices[0], 'status': '감지됨'})(),
        type('S', (), {'device': devices[1], 'status': '오프라인'})(),
        type('S', (), {'device': devices[2], 'status': '오프라인'})(),
        type('S', (), {'device': devices[3], 'status': '오프라인'})(),
    ]

    # 디버깅용 로그
    print("DEVICES:", devices)
    print("SENSORS:", sensors)

    # 테스트용 로컬 동영상 링크
    video_url = '/static/dashboard/videos/sample.mp4'

    return render(request, 'dashboard/home.html', {
        'devices': devices,
        'sensors': sensors,
        'video_url': video_url,
    })


# CCTV 스트림 생성기
def frame_gen(cap):
    classifier = SingletonClassifier()  # 분류기 인스턴스 (싱글톤)
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # --- 분류 수행 ---
        label, score = classifier.predict_bgr(frame)

        # --- 프레임 위에 결과 텍스트 오버레이 ---
        text = f"{label} ({score*100:.2f}%)"
        cv2.putText(frame, text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1, (0, 255, 0), 2, cv2.LINE_AA)

        # --- JPEG 인코딩 후 전송 ---
        _, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# CCTV 스트리밍 뷰
def cctv_stream(request):
    url = request.GET.get("url", "0")
    cap = cv2.VideoCapture(int(url) if url.isdigit() else url)
    return StreamingHttpResponse(
        frame_gen(cap),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

# 이미지 분류 API (업로드)
@csrf_exempt
def classify_image(request):
    if request.method == "POST" and "file" in request.FILES:
        uploaded = request.FILES["file"]
        # TODO: 실제 분류기 연동 (지금은 파일명만 반환)
        return JsonResponse({"ok": True, "filename": uploaded.name})
    return JsonResponse({"ok": False, "error": "No file"}, status=400)
