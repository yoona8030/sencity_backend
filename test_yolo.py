import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sencity_backend.settings")
django.setup()

from api.ai.yolo_utils import yolo_predict_image_file

# 테스트할 폴더 경로
IMAGE_DIR = r"C:\Users\a9349\2302553\test"

# 허용 이미지 확장자
VALID_EXT = [".jpg", ".jpeg", ".png", ".webp"]


def is_image(filename):
    return os.path.splitext(filename)[1].lower() in VALID_EXT


if __name__ == "__main__":
    print("=== YOLO 테스트 시작 ===")
    print(f"폴더: {IMAGE_DIR}")

    files = sorted(os.listdir(IMAGE_DIR))

    for filename in files:
        if not is_image(filename):
            continue

        img_path = os.path.join(IMAGE_DIR, filename)
        print(f"\n--- 이미지: {filename} ---")

        result = yolo_predict_image_file(img_path)
        print("RESULT:", result)
