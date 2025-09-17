# scripts/train.py
import os
from pathlib import Path
import tensorflow as tf
from tensorflow import keras

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 데이터셋 & 출력 위치
DATASET_DIR = Path(os.getenv("DATASET_DIR", r"C:\Users\a9349\datasets\animals"))
PROC_DIR = DATASET_DIR / "processed"  # prepare.py가 만든 곳
LABELS_TXT = PROC_DIR / "labels.txt"

# 프로젝트 내보내기 위치 (백엔드에서 바로 사용하는 SavedModel)
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # ...\sencity_backend
EXPORT_DIR = PROJECT_ROOT / "converted_savedmodel"
SAVEDMODEL_DIR = EXPORT_DIR / "model.savedmodel"

IMG_SIZE = int(os.getenv("IMG_SIZE", "224"))
BATCH = int(os.getenv("BATCH", "32"))
EPOCHS = int(os.getenv("EPOCHS", "5"))

def load_datasets():
    train_dir = PROC_DIR / "train"
    val_dir = PROC_DIR / "val"
    if not train_dir.exists() or not val_dir.exists():
        raise FileNotFoundError("processed/train or processed/val not found. Run prepare.py first.")

    train_ds = keras.utils.image_dataset_from_directory(
        train_dir, image_size=(IMG_SIZE, IMG_SIZE), batch_size=BATCH, label_mode="categorical"
    )
    val_ds = keras.utils.image_dataset_from_directory(
        val_dir, image_size=(IMG_SIZE, IMG_SIZE), batch_size=BATCH, label_mode="categorical"
    )

    # 성능을 위한 prefetch
    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.prefetch(AUTOTUNE)
    val_ds = val_ds.prefetch(AUTOTUNE)
    return train_ds, val_ds

def build_model(num_classes: int):
    base = keras.applications.mobilenet_v2.MobileNetV2(
        include_top=False, input_shape=(IMG_SIZE, IMG_SIZE, 3), weights="imagenet"
    )
    base.trainable = False  # 빠른 학습을 위해 head만
    inputs = keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
    x = keras.applications.mobilenet_v2.preprocess_input(inputs)
    x = base(x, training=False)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(0.2)(x)
    outputs = keras.layers.Dense(num_classes, activation="softmax")(x)
    model = keras.Model(inputs, outputs)
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model

def export_savedmodel(model: keras.Model):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Keras 3에서는 inference용 SavedModel을 export()로 손쉽게 생성
    # (서빙 시 signature: 'serving_default')
    if SAVEDMODEL_DIR.exists():
        # 덮어쓰기
        import shutil
        shutil.rmtree(SAVEDMODEL_DIR)
    model.export(str(SAVEDMODEL_DIR))  # <-- saved_model.pb 생성

    # labels.txt 복사(백엔드 predictor가 이 파일을 읽음)
    if LABELS_TXT.exists():
        (EXPORT_DIR / "labels.txt").write_text(LABELS_TXT.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"[OK] Exported SavedModel to: {SAVEDMODEL_DIR}")
    print(f"[OK] labels.txt written to: {EXPORT_DIR / 'labels.txt'}")

def main():
    # 클래스 수 파악
    if not LABELS_TXT.exists():
        raise FileNotFoundError(f"labels.txt not found: {LABELS_TXT} (run prepare.py first)")
    classes = [c.strip() for c in LABELS_TXT.read_text(encoding="utf-8").splitlines() if c.strip()]
    num_classes = len(classes)
    print("Classes:", classes)

    train_ds, val_ds = load_datasets()
    model = build_model(num_classes)
    model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS)
    export_savedmodel(model)

if __name__ == "__main__":
    main()
