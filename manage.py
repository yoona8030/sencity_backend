import os
import sys

def main():
    # ✅ Windows에서 OpenCV MSMF 충돌 방지: DSHOW/FFMPEG 우선 사용
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")
    # (선택) 일부 환경에서 발생하는 MKL/OMP 중복 로드 경고 완화
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sencity_backend.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
