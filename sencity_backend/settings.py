from pathlib import Path
from datetime import timedelta
import os, warnings
import environ   # ← 한 번만

BASE_DIR = Path(__file__).resolve().parent.parent

# 1) .env 먼저 로드
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# 2) Firebase 키 경로 보장
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    env("GOOGLE_APPLICATION_CREDENTIALS", default=r"C:\Users\a9349\sencity_keys\sencity-firebase.json")
)

# 3) Firebase 초기화 모듈 임포트
from sencity_backend import firebase_init  # noqa: F401


SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)
CSRF_TRUSTED_ORIGINS = [
  'http://127.0.0.1:8000',
  'http://localhost:8000',
  'https://dramaturgic-moneyed-cecelia.ngrok-free.dev'
]
ALLOWED_HOSTS = ['*', 'localhost', '127.0.0.1', '192.168.35.20', 'dramaturgic-moneyed-cecelia.ngrok-free.dev']
# 업로드 허용 이미지 타입 (views에서 재사용)
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
ALLOW_ANON_REPORTS = False

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework_simplejwt',
    'django.contrib.humanize',
    'django_filters',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'api',
    'cctv',
    'api.ai',
    'inquiries',
    "channels",
    'dashboard',
    'api.metrics.apps.MetricsConfig',
    'django_extensions',
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int('ACCESS_TOKEN_MIN', default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int('REFRESH_TOKEN_DAYS', default=7)),
    "ALGORITHM": "HS256",
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
    "LEEWAY": 30,
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sencity_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # 관리자 커스터마이징용 templates 디렉터리 추가
        'DIRS': [ BASE_DIR / 'templates' ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.static',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sencity_backend.wsgi.application'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        # 'rest_framework.authentication.SessionAuthentication',
        # "rest_framework.authentication.BasicAuthentication",
        # "rest_framework.authentication.TokenAuthentication",
        'api.authentication.CookieJWTAuthentication',  # 커스텀(헤더 없으면 쿠키에서)
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        # 개발 중 브라우저에서 API 확인 필요할 때만 주석 해제
        # 'rest_framework.renderers.BrowsableAPIRenderer',
        'sencity_backend.utils.renderers.UTF8JSONRenderer',

    ],
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
}

# --- CORS 설정 ---
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.35.20:8000",
    "https://dramaturgic-moneyed-cecelia.ngrok-free.dev"
]

# DB (sqlite 기본 / env로 덮어씀)
if env('DB_ENGINE', default='sqlite3') == 'sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / env('DB_NAME', default='db.sqlite3'),
            'OPTIONS': {'timeout': 10,}
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.' + env('DB_ENGINE'),
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST', default='127.0.0.1'),
            'PORT': env('DB_PORT', default='5432'),
        }
    }

# AI/분류기 설정 (settings에서 참조 가능)
DATASET_DIR = env('DATASET_DIR', default=None)
VAL_RATIO   = env.float('VAL_RATIO', default=0.2)
IMG_SIZE    = env.int('IMG_SIZE', default=224)
BATCH       = env.int('BATCH', default=32)
EPOCHS      = env.int('EPOCHS', default=5)

CLASSIFIER_LOAD_FN = env('CLASSIFIER_LOAD_FN', default=None)
CLASSIFIER_PRED_FN = env('CLASSIFIER_PRED_FN', default=None)
CLASSIFIER_WEIGHTS = env('CLASSIFIER_WEIGHTS', default=None)
CLASSIFIER_LABELS  = env('CLASSIFIER_LABELS', default=None)

YOLO_MODELS_DIR = BASE_DIR / "yolo_models"
YOLO_MODEL_FILENAME = env("YOLO_MODEL_FILENAME", default="best.pt")
YOLO_MODEL_PATH = str(YOLO_MODELS_DIR / YOLO_MODEL_FILENAME)

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators
AUTH_USER_MODEL = 'api.User'
AUTHENTICATION_BACKENDS = [
    'api.backends.EmailBackend',  # app명.backends.클래스이름
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'ko-kr'

TIME_ZONE = 'Asia/Seoul'

USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
# 개발 중 추가 정적 파일 경로
STATICFILES_DIRS = [ BASE_DIR / 'static' ]
# collectstatic 시 파일을 모을 디렉터리
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Media 파일(업로드) 설정 (필요 시)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

IMAGE_PROXY_ALLOWED_HOSTS = [
    "chosun.com",
]
# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 로그인/로그아웃 경로 설정 (리다이렉트 포함)
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'          # 로그인 성공 시 이동
LOGOUT_REDIRECT_URL = '/accounts/login/'    # 로그아웃 시 이동

ASGI_APPLICATION = "sencity_backend.asgi.application"

# 개발 단계: 메모리 채널 (운영은 Redis 권장)
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}

# --- 쿠키 보안 ---
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE   = 'Lax'
SESSION_COOKIE_SECURE   = False  # 운영(HTTPS)에서는 True
CSRF_COOKIE_SECURE      = False  # 운영(HTTPS)에서는 True

AI_INGEST_TOKEN = env("AI_INGEST_TOKEN", default="default-key")
AI_MIN_PROB = env.float("AI_MIN_PROB", default=0.5)
AI_SYSTEM_USERNAME = env("AI_SYSTEM_USERNAME", default="ai_bot")
