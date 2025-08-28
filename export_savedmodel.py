import os, tensorflow as tf
from tensorflow.keras.applications import mobilenet_v2

dst = r"C:\Users\a9349\sencity_backend\external\classification_model\converted_savedmodel\model.savedmodel"
os.makedirs(dst, exist_ok=True)

# 인터넷 가능: 사전학습 가중치
model = mobilenet_v2.MobileNetV2(weights="imagenet", include_top=True)

tf.saved_model.save(model, dst)
print("SavedModel ready:", os.path.exists(os.path.join(dst, "saved_model.pb")))
