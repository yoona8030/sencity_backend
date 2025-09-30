# Django 프로젝트 설정 및 사용법
# sencity_classification_model\django_settings.py

# 1. requirements.txt 에 추가할 패키지들
"""
tensorflow>=2.13.0
Pillow>=9.0.0
numpy>=1.21.0
"""

# 2. settings.py 에 추가할 설정
"""
# settings.py

import os
from pathlib import Path

# 모델 파일 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = os.path.join(BASE_DIR, 'ml_models')

# 미디어 파일 설정 (이미지 업로드용)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 업로드 파일 크기 제한 (10MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# 허용되는 이미지 형식
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
"""

# 3. apps.py 에서 모델 초기화
"""
# your_app/apps.py

from django.apps import AppConfig
from django.conf import settings
import os

class YourAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'your_app'

    def ready(self):
        # Django 서버 시작 시 모델을 한 번만 로드함
        try:
            from .utils.django_model_utils import initialize_classifier
            model_dir = getattr(settings, 'MODEL_DIR', './ml_models')
            initialize_classifier(model_dir)
            print("동물 분류 모델이 성공적으로 로드됨")
        except Exception as e:
            print(f"모델 로드 실패: {e}")
"""

# 4. urls.py 설정
"""
# your_app/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('predict/', views.predict_animal_api, name='predict_animal_api'),
    path('classify/', views.predict_animal_page, name='predict_animal_page'),
]

# 프로젝트 메인 urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('animal/', include('your_app.urls')),
]

# 미디어 파일 서빙 (개발 환경에서만)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
"""

# 5. views.py 완전한 예제
"""
# your_app/views.py

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from .utils.django_model_utils import predict_uploaded_image, predict_image_path, animal_classifier
import json
import os
import time

@csrf_exempt
@require_POST
def predict_animal_api(request):
    '''
    동물 이미지 분류 API 뷰
    POST 요청으로 이미지 파일을 받아 동물 종을 예측함
    '''
    try:
        # 업로드된 파일 확인
        if 'image' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': '이미지 파일이 필요함'
            }, status=400)

        uploaded_file = request.FILES['image']

        # 파일 크기 확인 (10MB 제한)
        if uploaded_file.size > 10 * 1024 * 1024:
            return JsonResponse({
                'success': False,
                'error': '파일 크기가 너무 큼 (최대 10MB)'
            }, status=400)

        # 파일 형식 확인
        allowed_types = getattr(settings, 'ALLOWED_IMAGE_TYPES',
                               ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'])
        if uploaded_file.content_type not in allowed_types:
            return JsonResponse({
                'success': False,
                'error': '지원하지 않는 파일 형식임 (JPEG, PNG, WebP만 지원)'
            }, status=400)

        # 예측 수행
        start_time = time.time()
        result = predict_uploaded_image(uploaded_file, top_k=3)
        prediction_time = time.time() - start_time

        # 응답에 처리 시간 추가
        if result['success']:
            result['prediction_time'] = round(prediction_time, 3)

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'서버 오류: {str(e)}'
        }, status=500)

@require_GET
def predict_animal_page(request):
    '''
    동물 분류 웹 페이지 뷰
    '''
    try:
        model_info = animal_classifier.get_model_info()
        context = {
            'model_info': model_info,
            'class_names': model_info['class_names'],
            'num_classes': model_info['num_classes']
        }
        return render(request, 'animal_classifier.html', context)
    except Exception as e:
        context = {
            'error': f'모델 정보를 가져올 수 없음: {str(e)}'
        }
        return render(request, 'animal_classifier.html', context)

@csrf_exempt
@require_POST
def predict_saved_image(request):
    '''
    서버에 저장된 이미지 파일에 대해 예측을 수행함
    '''
    try:
        data = json.loads(request.body)
        image_path = data.get('image_path')

        if not image_path:
            return JsonResponse({
                'success': False,
                'error': '이미지 경로가 필요함'
            }, status=400)

        # 보안을 위해 미디어 디렉토리 내의 파일만 허용
        full_path = os.path.join(settings.MEDIA_ROOT, image_path)
        if not os.path.exists(full_path):
            return JsonResponse({
                'success': False,
                'error': '파일을 찾을 수 없음'
            }, status=404)

        # 예측 수행
        result = predict_image_path(full_path, top_k=3)

        return JsonResponse(result)

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '잘못된 JSON 형식'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'서버 오류: {str(e)}'
        }, status=500)

@require_GET
def get_model_info(request):
    '''
    모델 정보를 반환하는 API
    '''
    try:
        model_info = animal_classifier.get_model_info()
        return JsonResponse({
            'success': True,
            'model_info': model_info
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'모델 정보를 가져올 수 없음: {str(e)}'
        }, status=500)
"""

# 6. HTML 템플릿 예제
"""
<!-- templates/animal_classifier.html -->

<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>동물 분류기</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .upload-area { border: 2px dashed #ccc; padding: 20px; text-align: center; margin: 20px 0; }
        .upload-area:hover { border-color: #999; }
        .result { margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 5px; }
        .class-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0; }
        .class-item { padding: 10px; background: #e9ecef; border-radius: 5px; text-align: center; }
        .prediction-item { margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }
        .progress-bar { width: 100%; height: 20px; background: #f0f0f0; border-radius: 10px; overflow: hidden; }
        .progress-fill { height: 100%; background: #007bff; transition: width 0.3s ease; }
        .error { color: #dc3545; }
        .success { color: #28a745; }
    </style>
</head>
<body>
    <h1>동물 분류기</h1>

    {% if error %}
        <div class="error">{{ error }}</div>
    {% else %}
        <div class="model-info">
            <h3>모델 정보</h3>
            <p>분류 가능한 동물 수: {{ model_info.num_classes }}종</p>
            <p>입력 이미지 크기: {{ model_info.input_size }}x{{ model_info.input_size }}</p>
        </div>

        <div class="class-list">
            <h3>분류 가능한 동물들:</h3>
            {% for class_name in class_names %}
                <div class="class-item">{{ class_name }}</div>
            {% endfor %}
        </div>
    {% endif %}

    <div class="upload-area" onclick="document.getElementById('fileInput').click()">
        <p>이미지를 선택하거나 여기에 드래그하세요</p>
        <input type="file" id="fileInput" accept="image/*" style="display: none;">
    </div>

    <div id="imagePreview" style="display: none;">
        <h3>선택된 이미지:</h3>
        <img id="previewImg" style="max-width: 300px; height: auto;">
    </div>

    <button id="predictBtn" style="display: none; padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 5px;">
        예측하기
    </button>

    <div id="loading" style="display: none;">예측 중...</div>

    <div id="result" style="display: none;"></div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const imagePreview = document.getElementById('imagePreview');
        const previewImg = document.getElementById('previewImg');
        const predictBtn = document.getElementById('predictBtn');
        const loading = document.getElementById('loading');
        const result = document.getElementById('result');

        fileInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    previewImg.src = e.target.result;
                    imagePreview.style.display = 'block';
                    predictBtn.style.display = 'block';
                };
                reader.readAsDataURL(file);
            }
        });

        predictBtn.addEventListener('click', function() {
            const file = fileInput.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('image', file);

            loading.style.display = 'block';
            result.style.display = 'none';
            predictBtn.disabled = true;

            fetch('/animal/predict/', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                loading.style.display = 'none';
                predictBtn.disabled = false;

                if (data.success) {
                    let html = '<div class="result success">';
                    html += '<h3>예측 결과</h3>';
                    html += `<p><strong>예측된 동물:</strong> ${data.predicted_class}</p>`;
                    html += `<p><strong>신뢰도:</strong> ${data.confidence_percent}%</p>`;
                    html += `<p><strong>처리 시간:</strong> ${data.prediction_time}초</p>`;

                    html += '<h4>상위 3개 예측:</h4>';
                    data.top_predictions.forEach(pred => {
                        html += '<div class="prediction-item">';
                        html += `<div>${pred.class_name}: ${pred.confidence_percent}%</div>`;
                        html += '<div class="progress-bar">';
                        html += `<div class="progress-fill" style="width: ${pred.confidence_percent}%"></div>`;
                        html += '</div></div>';
                    });

                    html += '</div>';
                    result.innerHTML = html;
                } else {
                    result.innerHTML = `<div class="result error">오류: ${data.error}</div>`;
                }

                result.style.display = 'block';
            })
            .catch(error => {
                loading.style.display = 'none';
                predictBtn.disabled = false;
                result.innerHTML = `<div class="result error">요청 실패: ${error}</div>`;
                result.style.display = 'block';
            });
        });

        // 드래그 앤 드롭 기능
        const uploadArea = document.querySelector('.upload-area');

        uploadArea.addEventListener('dragover', function(e) {
            e.preventDefault();
            uploadArea.style.borderColor = '#007bff';
        });

        uploadArea.addEventListener('dragleave', function(e) {
            e.preventDefault();
            uploadArea.style.borderColor = '#ccc';
        });

        uploadArea.addEventListener('drop', function(e) {
            e.preventDefault();
            uploadArea.style.borderColor = '#ccc';

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                fileInput.dispatchEvent(new Event('change'));
            }
        });
    </script>
</body>
</html>
"""

# 7. 디렉토리 구조
"""
your_django_project/
├── manage.py
├── your_project/
│   ├── settings.py
│   ├── urls.py
│   └── ...
├── your_app/
│   ├── __init__.py
│   ├── apps.py
│   ├── views.py
│   ├── urls.py
│   ├── utils/
│   │   └── django_model_utils.py
│   └── templates/
│       └── animal_classifier.html
├── ml_models/  # 훈련된 모델 파일들을 여기에 저장
│   ├── animal_classifier.h5
│   ├── animal_classifier_savedmodel/
│   └── class_info.json
├── media/  # 업로드된 이미지 파일들
└── requirements.txt
"""

# 8. 배포 시 주의사항
"""
배포 시 고려사항:

1. 메모리 사용량: TensorFlow 모델은 메모리를 많이 사용함
   - 서버 메모리를 충분히 확보해야 함 (최소 2GB 이상 권장)

2. CPU vs GPU:
   - CPU만으로도 추론 가능하지만 GPU가 있으면 더 빠름
   - 서버에 GPU가 없다면 tensorflow-cpu 버전 사용 권장

3. 모델 파일 크기:
   - EfficientNet 모델은 약 20-30MB 정도의 크기를 가짐
   - Git에 모델 파일을 포함하지 말고 별도로 업로드하는 것이 좋음

4. 동시 요청 처리:
   - 모델은 앱 시작 시 한 번만 로드하고 재사용함
   - 동시 요청이 많을 경우 큐잉 시스템 고려

5. 이미지 전처리 최적화:
   - Pillow 대신 OpenCV 사용 고려 (더 빠른 이미지 처리)
   - 이미지 캐싱 시스템 도입 고려
"""

# 9. 테스트용 스크립트
"""
# test_model.py - 모델 테스트용 스크립트

import os
from your_app.utils.django_model_utils import AnimalClassifier

def test_model():
    '''모델이 제대로 작동하는지 테스트함'''

    # 모델 경로 설정
    model_dir = './ml_models'
    model_path = os.path.join(model_dir, 'animal_classifier.h5')
    class_info_path = os.path.join(model_dir, 'class_info.json')

    # 분류기 초기화
    classifier = AnimalClassifier(model_path, class_info_path)

    # 모델 정보 출력
    info = classifier.get_model_info()
    print("모델 정보:", info)

    # 테스트 이미지로 예측 수행 (테스트 이미지 경로 필요)
    test_image_path = './test_images/test_cat.jpg'  # 실제 테스트 이미지 경로
    if os.path.exists(test_image_path):
        result = classifier.predict(test_image_path, is_file_path=True)
        print("예측 결과:", result)
    else:
        print("테스트 이미지가 없음")

if __name__ == "__main__":
    test_model()
"""
