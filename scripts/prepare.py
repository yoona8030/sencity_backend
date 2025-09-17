# scripts/prepare.py
import os, random, shutil
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 원천 데이터셋 루트 (클래스별 폴더 구조)
DATASET_DIR = os.getenv("DATASET_DIR", r"C:\Users\a9349\datasets\animals")
RAW_DIR = Path(DATASET_DIR) / "raw"   # 예: C:\Users\a9349\datasets\animals\raw\고양이\*.jpg
OUT_DIR = Path(DATASET_DIR) / "processed"  # train/val 생성 위치
VAL_RATIO = float(os.getenv("VAL_RATIO", "0.2"))
SEED = int(os.getenv("SEED", "42"))

def split_train_val():
    if not RAW_DIR.exists():
        raise FileNotFoundError(f"RAW_DIR not found: {RAW_DIR}")

    random.seed(SEED)
    # 클래스 폴더 나열
    classes = sorted([d.name for d in RAW_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")])
    if not classes:
        raise RuntimeError(f"No class folders in {RAW_DIR}")

    # 출력 구조 초기화
    for split in ("train", "val"):
        split_dir = OUT_DIR / split
        if split_dir.exists():
            shutil.rmtree(split_dir)
        split_dir.mkdir(parents=True, exist_ok=True)
        for c in classes:
            (split_dir / c).mkdir(parents=True, exist_ok=True)

    # 이미지 분할 & 복사 (심플 버전)
    for c in classes:
        files = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
            files += list((RAW_DIR / c).glob(ext))
        files = sorted(files)
        if not files:
            print(f"[WARN] No images in class {c}")
            continue

        random.shuffle(files)
        n_val = int(len(files) * VAL_RATIO)
        val_files = set(files[:n_val])

        for f in files:
            split = "val" if f in val_files else "train"
            dst = OUT_DIR / split / c / f.name
            shutil.copy2(f, dst)

    # labels.txt (클래스명 줄바꿈)
    labels_path = OUT_DIR / "labels.txt"
    labels_path.write_text("\n".join(classes), encoding="utf-8")
    print(f"[OK] Split done.\n - Train: {sum(len(list((OUT_DIR/'train'/c).glob('*'))) for c in classes)}"
          f"\n - Val  : {sum(len(list((OUT_DIR/'val'/c).glob('*'))) for c in classes)}"
          f"\n - Labels: {labels_path}")

if __name__ == "__main__":
    split_train_val()
