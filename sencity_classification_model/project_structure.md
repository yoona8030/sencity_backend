# 🗂️ Sencity 동물 분류 프로젝트 구조

## 📁 1단계: 모델 훈련 프로젝트 구조

```
sencity_classification_model/
├── train_model.py              # 메인 훈련 스크립트 (동물 분류 EfficientNet 모델)
├── requirements.txt            # 필요한 패키지들
├── data/                       # 훈련 데이터 폴더
│   ├── Goat/                  # 염소 이미지 500장
│   ├── Wild boar/             # 멧돼지 이미지 500장
│   ├── Squirrel/              # 다람쥐 이미지 500장
│   ├── Raccoon/               # 너구리 이미지 500장
│   ├── Asiatic black bear/    # 반달가슴곰 이미지 500장
│   ├── Hare/                  # 토끼 이미지 500장
│   ├── Weasel/                # 족제비 이미지 500장
│   ├── Heron/                 # 왜가리 이미지 500장
│   ├── Dog/                   # 개 이미지 500장
│   └── Cat/                   # 고양이 이미지 500장
└── models/                     # 훈련 완료 후 생성되는 폴더
    ├── animal_classifier.h5          # Django용 모델 파일 ⭐
    ├── class_info.json               # 클래스 정보 파일 ⭐
    ├── animal_classifier_savedmodel/ # SavedModel 형식
    ├── data_split_info.txt           # 데이터 분할 정보
    ├── training_history.png          # 훈련 과정 그래프
    └── best_finetuned_model.h5       # 최고 성능 모델
```

## 📁 2단계: Django 프로젝트 구조

```
your_django_project/
├── manage.py
├── requirements.txt            # Django + TensorFlow 패키지들
├── your_project/
│   ├── settings.py            # Django 설정 및 사용법 내용 추가
│   ├── urls.py
│   └── ...
├── animal_classifier_app/      # 동물 분류 앱
│   ├── __init__.py
│   ├── apps.py                # 모델 자동 로딩 설정
│   ├── views.py               # API 엔드포인트
│   ├── urls.py                # URL 매핑
│   ├── utils/
│   │   └── django_model_utils.py  # Django용 모델 유틸리티 ⭐
│   └── templates/
│       └── animal_classifier.html
├── ml_models/                  # 훈련된 모델 파일들 복사
│   ├── animal_classifier.h5          # 복사해온 파일 ⭐
│   └── class_info.json               # 복사해온 파일 ⭐
├── media/                      # 업로드된 이미지들
└── static/                     # CSS, JS 파일들
```

## 🚀 **실행 순서**

### 1단계: 모델 훈련
```bash
# 프로젝트 폴더 생성
mkdir sencity_classification_model
cd sencity_classification_model

# 데이터 폴더 준비
mkdir data
# data 폴더에 각 동물별 하위 폴더 생성하고 이미지 500장씩 넣기

# 훈련 스크립트 실행
python train_model.py
```

### 2단계: Django 프로젝트에 통합
```bash
# Django 프로젝트로 이동
cd your_django_project

# 모델 파일들 복사
cp sencity_classification_model/models/animal_classifier.h5 ml_models/
cp sencity_classification_model/models/class_info.json ml_models/

# Django 서버 실행
python manage.py runserver
```

## 📋 **체크리스트**

### ✅ 모델 훈련 단계
- [ ] `sencity_classification_model/` 폴더 생성
- [ ] `data/` 폴더에 10개 동물별 이미지 500장씩 준비
- [ ] `train_model.py` 실행
- [ ] `models/` 폴더에 `.h5`와 `.json` 파일 생성 확인

### ✅ Django 통합 단계  
- [ ] Django 프로젝트에 `ml_models/` 폴더 생성
- [ ] 훈련된 모델 파일 2개 복사
- [ ] `django_model_utils.py` 앱에 추가
- [ ] `settings.py`, `apps.py`, `views.py` 설정
- [ ] 웹 인터페이스 테스트

## 📝 **핵심 포인트**

1. **데이터 경로**: 코드에서 `DATA_DIR = './data'`로 설정되어 있어서 `sencity_classification_model/data/` 구조가 맞음

2. **자동 생성 파일**: 훈련 완료 후 `models/` 폴더에 Django용 파일들이 자동 생성됨

3. **Django 이전**: 생성된 `.h5`와 `.json` 파일만 Django 프로젝트로 복사하면 됨

4. **독립적 실행**: 모델 훈련과 Django 서버는 별도 환경에서 실행 가능

이렇게 하면 모델 훈련부터 Django 웹 서비스까지 완벽하게 연동됩니다!