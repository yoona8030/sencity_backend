# train_model.py
import os
from pathlib import Path

import tensorflow as tf
from tensorflow import keras

# ---- Keras 하위 모듈은 keras 경유로만 사용 (TF2.16 권장 방식) ----
layers = keras.layers
EfficientNetB0 = keras.applications.EfficientNetB0
ImageDataGenerator = keras.preprocessing.image.ImageDataGenerator
ModelCheckpoint = keras.callbacks.ModelCheckpoint
EarlyStopping = keras.callbacks.EarlyStopping
ReduceLROnPlateau = keras.callbacks.ReduceLROnPlateau
TopKCategoricalAccuracy = keras.metrics.TopKCategoricalAccuracy

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

K = tf.keras.backend
K.set_image_data_format('channels_last')
print("[DEBUG] image_data_format =", K.image_data_format())

try:
    font_manager.fontManager.addfont(r"C:\Windows\Fonts\malgun.ttf")     # Regular
    font_manager.fontManager.addfont(r"C:\Windows\Fonts\malgunbd.ttf")   # Bold (선택)
except Exception:
    # 폰트가 없더라도 실행은 계속
    pass

rcParams["font.family"] = "Malgun Gothic"
rcParams["axes.unicode_minus"] = False  # 마이너스 부호 깨짐 방지

# ==========================
# 환경/하이퍼파라미터
# ==========================
# 필요 시 oneDNN 최적화로 인한 미세한 수치 차이를 없애려면, 실행 전에:
#   set TF_ENABLE_ONEDNN_OPTS=0  (Windows CMD)
#   $env:TF_ENABLE_ONEDNN_OPTS=0 (PowerShell)

# GPU 메모리 증가 방식 설정(선택)
gpus = tf.config.experimental.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
    except RuntimeError as e:
        print(e)

IMG_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 50
LEARNING_RATE = 0.001
NUM_CLASSES = 10

CLASS_NAMES = [
    'Goat', 'Wild boar', 'Squirrel', 'Raccoon', 'Asiatic black bear',
    'Hare', 'Weasel', 'Heron', 'Dog', 'Cat'
]

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODEL_SAVE_PATH = BASE_DIR / "models"

TRAIN_SPLIT = 0.70
VALIDATION_SPLIT = 0.20
TEST_SPLIT = 0.10

# 디렉터리 준비
MODEL_SAVE_PATH.mkdir(parents=True, exist_ok=True)

# data 폴더/클래스 폴더 존재 점검(명확한 에러 메시지 제공)
if not DATA_DIR.exists():
    raise FileNotFoundError(f"[DATA_DIR 없음] {DATA_DIR}")

expected = set(CLASS_NAMES)
actual = {p.name for p in DATA_DIR.iterdir() if p.is_dir()}
missing = expected - actual
if missing:
    raise RuntimeError(
        "data/ 폴더에 아래 클래스 디렉터리가 없습니다:\n"
        + "\n".join(f"- {m}" for m in sorted(missing))
        + "\n(폴더 이름은 CLASS_NAMES와 정확히 일치해야 합니다.)"
    )


# ==========================
# 데이터 생성기
# ==========================
def create_data_generators():
    # 공통 전처리: EfficientNet 전처리만 적용 (rescale 제거!)
    common_kwargs = dict(
        preprocessing_function=tf.keras.applications.efficientnet.preprocess_input,
        validation_split=VALIDATION_SPLIT + TEST_SPLIT,
    )
    datagen = ImageDataGenerator(**common_kwargs)

    train_datagen = ImageDataGenerator(
        rotation_range=20,
        width_shift_range=0.2,
        height_shift_range=0.2,
        shear_range=0.2,
        zoom_range=0.2,
        horizontal_flip=True,
        fill_mode='nearest',
        **common_kwargs
    )

    train_generator = train_datagen.flow_from_directory(
        str(DATA_DIR),
        target_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        class_mode='categorical',
        subset='training',
        classes=CLASS_NAMES,
        shuffle=True,
        seed=42,
        color_mode='rgb',
    )

    val_test_generator = datagen.flow_from_directory(
        str(DATA_DIR),
        target_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        class_mode='categorical',
        subset='validation',
        classes=CLASS_NAMES,
        shuffle=False,
        seed=42,
        color_mode='rgb',
    )

    val_test_samples = val_test_generator.samples
    val_samples = int(val_test_samples * (VALIDATION_SPLIT / (VALIDATION_SPLIT + TEST_SPLIT)))

    print("전체 데이터 분할:")
    print(f"  훈련: {train_generator.samples}장")
    print(f"  검증(추정): {val_samples}장")
    print(f"  테스트(추정): {val_test_samples - val_samples}장")

    return train_generator, val_test_generator, val_samples


# ==========================
# 모델 정의/컴파일
# ==========================
def create_model():
    inputs = keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3), name="input_layer")
    x = inputs  # 전처리는 제너레이터에서 수행

    backbone = tf.keras.applications.efficientnet.EfficientNetB0(
        weights="imagenet",
        include_top=False,
    )
    backbone.trainable = False

    x = backbone(x, training=False)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(0.3)(x)
    x = keras.layers.Dense(128, activation="relu")(x)
    x = keras.layers.Dropout(0.2)(x)
    outputs = keras.layers.Dense(NUM_CLASSES, activation="softmax")(x)

    model = keras.Model(inputs, outputs, name="animal_classifier")
    return model, backbone


def compile_model(model):
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss='categorical_crossentropy',
        metrics=['accuracy', TopKCategoricalAccuracy(k=2, name='top_2_accuracy')],
    )
    return model


def create_callbacks():
    return [
        keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(MODEL_SAVE_PATH, 'best_model.keras'),
            monitor='val_accuracy',
            save_best_only=True,
            save_weights_only=False,
            mode='max',
            verbose=1,
        ),
        keras.callbacks.EarlyStopping(
            monitor='val_accuracy',
            patience=10,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.2,
            patience=5,
            min_lr=1e-7,
            verbose=1,
        ),
    ]
    return callbacks


# ==========================
# 평가/시각화
# ==========================
def evaluate_on_test_set(model, val_test_generator, val_samples):
    print("\n테스트 세트에서 최종 평가를 수행함...")
    test_loss, test_accuracy, test_top2_accuracy = model.evaluate(val_test_generator, verbose=1)
    print("테스트 결과:")
    print(f"  손실: {test_loss:.4f}")
    print(f"  정확도: {test_accuracy:.4f}")
    print(f"  Top-2 정확도: {test_top2_accuracy:.4f}")
    return test_loss, test_accuracy, test_top2_accuracy


def plot_training_history(history):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(history.history['accuracy'], label='훈련 정확도')
    ax1.plot(history.history['val_accuracy'], label='검증 정확도')
    ax1.set_title('Model Accuracy')
    ax1.set_xlabel('Epoch')
    ax1.set_ylabel('Accuracy')
    ax1.legend()

    ax2.plot(history.history['loss'], label='훈련 손실')
    ax2.plot(history.history['val_loss'], label='검증 손실')
    ax2.set_title('Model Loss')
    ax2.set_xlabel('Epoch')
    ax2.set_ylabel('Loss')
    ax2.legend()

    plt.tight_layout()
    out = MODEL_SAVE_PATH / 'training_history.png'
    plt.savefig(out)
    print(f"학습 곡선 저장: {out}")


# ==========================
# 저장(Serving)
# ==========================
def save_model_for_deployment(model):
    # SavedModel (폴더)
    savedmodel_path = os.path.join(MODEL_SAVE_PATH, 'animal_classifier_savedmodel')
    model.export(savedmodel_path)  # Keras 3 방식

    # Keras 단일 파일
    keras_path = os.path.join(MODEL_SAVE_PATH, 'animal_classifier.keras')  # <<< 변경
    model.save(keras_path)

    # class_info.json 저장 (그대로 유지)
    import json
    class_info = {
        'class_names': CLASS_NAMES,
        'num_classes': NUM_CLASSES,
        'input_size': IMG_SIZE,
        'train_split': TRAIN_SPLIT,
        'validation_split': VALIDATION_SPLIT,
        'test_split': TEST_SPLIT,
        'total_samples_per_class': 500,
        'model_architecture': 'EfficientNetB0',
        'training_epochs': EPOCHS,
        'batch_size': BATCH_SIZE
    }
    class_info_path = os.path.join(MODEL_SAVE_PATH, 'class_info.json')
    with open(class_info_path, 'w', encoding='utf-8') as f:
        json.dump(class_info, f, ensure_ascii=False, indent=2)

    print("모델과 설정 파일 저장 완료:")
    print(f"  SavedModel: {savedmodel_path}")
    print(f"  Keras 모델: {keras_path}")
    print(f"  클래스 정보: {class_info_path}")

# ==========================
# 데이터 분할 요약(동적 집계)
# ==========================
def create_data_split_summary_dynamic():
    """
    data/ 각 클래스 폴더의 실제 이미지 개수를 집계해 요약 파일 저장
    """
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    lines = []
    total_images = 0
    per_class = {}

    for cls in CLASS_NAMES:
        cls_dir = DATA_DIR / cls
        n = sum(1 for p in cls_dir.rglob("*") if p.suffix.lower() in exts)
        per_class[cls] = n
        total_images += n
        lines.append(f"- {cls}: {n}장")

    train_est = int(total_images * TRAIN_SPLIT)
    val_est = int(total_images * VALIDATION_SPLIT)
    test_est = total_images - train_est - val_est

    summary = (
        "동물 분류 모델 데이터 분할 정보 (실제 파일 집계)\n"
        "============================================\n\n"
        f"총 클래스 수: {NUM_CLASSES}개\n"
        f"전체 이미지 수(합계): {total_images}장\n\n"
        "클래스별 이미지 수:\n" + "\n".join(lines) + "\n\n"
        "데이터 분할(비율 기준 예상치):\n"
        f"- 훈련 데이터 (~{TRAIN_SPLIT*100:.0f}%): {train_est}장\n"
        f"- 검증 데이터 (~{VALIDATION_SPLIT*100:.0f}%): {val_est}장\n"
        f"- 테스트 데이터 (~{TEST_SPLIT*100:.0f}%): {test_est}장\n"
    )

    out_path = MODEL_SAVE_PATH / "data_split_info.txt"
    out_path.write_text(summary, encoding="utf-8")
    print(f"요약 저장: {out_path}")


# ==========================
# 메인
# ==========================
def main():
    print("동물 분류 모델 훈련을 시작함...")
    print(f"분류할 동물 종: {CLASS_NAMES}")
    print(f"분할 비율: train {TRAIN_SPLIT:.0%} | val {VALIDATION_SPLIT:.0%} | test {TEST_SPLIT:.0%}")

    # 1) 데이터 요약(실제 개수 집계)
    create_data_split_summary_dynamic()

    # 2) 데이터 제너레이터
    print("\n데이터 제너레이터 생성...")
    train_generator, val_test_generator, val_samples = create_data_generators()

    # 3) 모델 생성/컴파일
    print("\n모델 생성/컴파일...")
    model, backbone = create_model()         # ← backbone 함께 받기
    model = compile_model(model)
    model.summary()

    # 4) 콜백
    callbacks = create_callbacks() # 1단계 저장

    # 5) 1단계: 전이학습
    print("\n[1단계] 전이학습 진행...")
    history1 = model.fit(
        train_generator,
        epochs=EPOCHS // 2,
        validation_data=val_test_generator,
        callbacks=callbacks,
        verbose=1
    )

    # 6) 2단계: 미세조정
    print("\n[2단계] 미세조정 진행...")
    backbone.trainable = True  # 백본 해제
    fine_tune_at = max(0, len(backbone.layers) - 20) # 상위 20개만 학습
    for layer in backbone.layers[:fine_tune_at]:
        layer.trainable = False

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE / 10),
        loss='categorical_crossentropy',
        metrics=['accuracy', TopKCategoricalAccuracy(k=2, name='top_2_accuracy')]
    )
    # best finetuned 파일 경로 갱신
    # 미세 조정용 콜백 업데이트
    callbacks[0].filepath = os.path.join(MODEL_SAVE_PATH, 'best_finetuned_model.keras')  # <<< 변경


    history2 = model.fit(
        train_generator,
        epochs=EPOCHS // 2,
        validation_data=val_test_generator,
        callbacks=callbacks,
        verbose=1
    )

    # 7) 히스토리 병합 & 시각화
    combined_history = {
        'accuracy': history1.history['accuracy'] + history2.history['accuracy'],
        'val_accuracy': history1.history['val_accuracy'] + history2.history['val_accuracy'],
        'loss': history1.history['loss'] + history2.history['loss'],
        'val_loss': history1.history['val_loss'] + history2.history['val_loss'],
    }

    class CombinedHistory:
        def __init__(self, h): self.history = h

    plot_training_history(CombinedHistory(combined_history))

    # 8) 평가
    print("\n검증 세트 평가:")
    val_loss, val_acc, val_top2 = model.evaluate(val_test_generator, verbose=1)
    print(f"검증 손실: {val_loss:.4f} | 검증 정확도: {val_acc:.4f} | 검증 Top-2: {val_top2:.4f}")

    # 9) 테스트(근사)
    _ = evaluate_on_test_set(model, val_test_generator, val_samples)

    # 10) 저장
    print("\nDjango 배포용 저장...")
    save_model_for_deployment(model)

    print("\n모델 훈련이 완료되었습니다!")


# ==========================
# 단일 이미지 예측 유틸
# ==========================
def predict_animal(model_path, image_path, class_names=CLASS_NAMES):
    model = keras.models.load_model(model_path)
    img = keras.preprocessing.image.load_img(image_path, target_size=(IMG_SIZE, IMG_SIZE))
    arr = keras.preprocessing.image.img_to_array(img)
    arr = np.expand_dims(arr, axis=0) / 255.0
    preds = model.predict(arr, verbose=0)[0]
    idx = int(np.argmax(preds))
    return {
        'predicted_class': class_names[idx],
        'confidence': float(preds[idx]),
        'class_probabilities': {class_names[i]: float(p) for i, p in enumerate(preds)}
    }


if __name__ == "__main__":
    main()
