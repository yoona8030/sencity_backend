import torch
import cv2
import numpy as np
from datetime import datetime
import os
import time
import threading
import base64
from io import BytesIO

class DjangoAnimalDetector:
    def __init__(self, model_path=None, confidence=0.5):
        # 모델 경로 자동 감지
        if model_path is None:
            import os
            from django.conf import settings

            # 여러 경로 후보들 시도
            candidates = [
                'animal_model.pt',  # 프로젝트 루트
                os.path.join(settings.BASE_DIR, 'animal_model.pt'),
                os.path.join(settings.MEDIA_ROOT, 'models', 'animal_model.pt'),
                os.path.join(settings.BASE_DIR, 'models', 'animal_model.pt'),
            ]

            for path in candidates:
                if os.path.exists(path):
                    model_path = path
                    break

            if model_path is None:
                raise FileNotFoundError("animal_model.pt 파일을 찾을 수 없습니다. 경로를 확인하세요.")

        print(f"모델 경로: {os.path.abspath(model_path)}")
        self.model_path = model_path
        self.confidence = confidence
        self.is_running = False
        self.current_frame = None
        self.detection_results = []

        # 동물 클래스 (영어-한국어)
        self.classes = ['Goat', 'Wild boar', 'Squirrel', 'Raccoon', 'Asiatic black bear',
                       'Hare', 'Weasel', 'Heron', 'Dog', 'Cat']
        self.korean_names = ['고라니', '멧돼지', '다람쥐', '너구리', '반달가슴곰',
                            '멧토끼', '족제비', '왜가리', '개', '고양이']

        # 저장 폴더 생성
        self.save_dir = 'media/detected_animals'
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

        self._load_model()

    def _load_model(self):
        try:
            self.model = torch.hub.load('ultralytics/yolov5', 'custom',
                                      path=self.model_path, force_reload=False, trust_repo=True)
            self.model.conf = self.confidence
            print(f"모델 로드 완료")
        except Exception as e:
            print(f"모델 로드 실패: {e}")
            raise

    def detect_frame(self, frame):
        try:
            results = self.model(frame)
            detections = []

            for *box, conf, cls in results.xyxy[0].cpu().numpy():
                if int(cls) < len(self.classes):
                    detections.append({
                        'animal_name': self.classes[int(cls)],
                        'korean_name': self.korean_names[int(cls)],
                        'confidence': float(conf),
                        'bbox': [int(x) for x in box]
                    })
            return detections
        except Exception as e:
            print(f"감지 오류: {e}")
            return []

    def start_stream_detection(self, stream_url, save_callback=None):
        def stream_worker():
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                print(f"스트림 연결 실패: {stream_url}")
                return

            print(f"스트림 감지 시작: {stream_url}")
            self.is_running = True
            frame_count = 0
            last_save_time = {}
            save_cooldown = 5

            while self.is_running:
                ret, frame = cap.read()
                if not ret:
                    break

                self.current_frame = frame.copy()
                frame_count += 1

                # 2프레임마다 감지
                if frame_count % 2 == 0:
                    detections = self.detect_frame(frame)
                    self.detection_results = detections

                    # 동물 감지 시 자동 저장
                    for detection in detections:
                        korean_name = detection['korean_name']
                        current_time = time.time()

                        if (korean_name not in last_save_time or
                            current_time - last_save_time[korean_name] > save_cooldown):

                            # 이미지 저장
                            saved_path = self.save_detection_image(frame, detection)
                            last_save_time[korean_name] = current_time

                            if save_callback and saved_path:
                                save_callback(detection, saved_path)

                time.sleep(0.03)

            cap.release()
            self.is_running = False
            print("스트림 감지 종료")

        self.stream_thread = threading.Thread(target=stream_worker)
        self.stream_thread.daemon = True
        self.stream_thread.start()

    def stop_stream_detection(self):
        self.is_running = False
        if hasattr(self, 'stream_thread'):
            self.stream_thread.join(timeout=2)

    def save_detection_image(self, frame, detection):
        """감지된 동물 이미지 저장"""
        try:
            korean_name = detection['korean_name']
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{korean_name}_{timestamp}.jpg"
            filepath = os.path.join(self.save_dir, filename)

            cv2.imwrite(filepath, frame)
            print(f"{korean_name} 저장: {filepath}")
            return filepath
        except Exception as e:
            print(f"저장 오류: {e}")
            return None

    def get_current_frame_base64(self):
        if self.current_frame is None:
            return None

        try:
            # 감지 결과 박스 그리기
            frame_with_boxes = self.current_frame.copy()
            for detection in self.detection_results:
                x1, y1, x2, y2 = detection['bbox']
                korean_name = detection['korean_name']
                confidence = detection['confidence']

                cv2.rectangle(frame_with_boxes, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame_with_boxes, f"{korean_name}: {confidence:.2f}",
                           (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # base64 인코딩
            _, buffer = cv2.imencode('.jpg', frame_with_boxes)
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            return f"data:image/jpeg;base64,{img_base64}"
        except Exception as e:
            print(f"프레임 인코딩 오류: {e}")
            return None


# Django views.py에서 사용할 전역 감지기
global_detector = None

def start_animal_detection(stream_url, confidence=0.5, save_callback=None):
    """
    Django view에서 호출할 함수

    Args:
        stream_url: 웹캠 스트림 URL
        confidence: 감지 신뢰도 (0.1~0.9)
        save_callback: 감지 시 호출할 함수 (Django 모델 저장용)

    Returns:
        bool: 시작 성공 여부
    """
    global global_detector

    try:
        # 기존 감지기 중지
        if global_detector:
            global_detector.stop_stream_detection()

        # 새 감지기 시작
        global_detector = DjangoAnimalDetector(confidence=confidence)
        global_detector.start_stream_detection(stream_url, save_callback)
        return True
    except Exception as e:
        print(f"감지 시작 오류: {e}")
        return False

def stop_animal_detection():
    """Django view에서 호출할 감지 중지 함수"""
    global global_detector
    if global_detector:
        global_detector.stop_stream_detection()
        global_detector = None
        return True
    return False

def get_detection_status():
    """현재 감지 상태 반환"""
    global global_detector
    if not global_detector:
        return {
            'is_running': False,
            'detections': [],
            'frame': None
        }

    return {
        'is_running': global_detector.is_running,
        'detections': global_detector.detection_results,
        'frame': global_detector.get_current_frame_base64(),
        'total_animals': len(global_detector.detection_results)
    }

# Django views.py 예시
"""
from .django_integration import start_animal_detection, stop_animal_detection, get_detection_status
from django.http import JsonResponse
import json

def start_detection_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        stream_url = data.get('stream_url')
        confidence = data.get('confidence', 0.5)

        def save_to_db(detection, image_path):
            # 여기서 Django 모델에 저장
            # DetectedAnimal.objects.create(
            #     animal_name=detection['korean_name'],
            #     confidence=detection['confidence'],
            #     image_path=image_path
            # )
            pass

        success = start_animal_detection(stream_url, confidence, save_to_db)
        return JsonResponse({'success': success})

def detection_status_view(request):
    status = get_detection_status()
    return JsonResponse(status)

def stop_detection_view(request):
    success = stop_animal_detection()
    return JsonResponse({'success': success})
"""
