# classifier_model_inference.py
import torch
from torchvision import models, transforms
from PIL import Image


# 모델 로드 함수
def load_model(model_path):
    # 모델 구조 생성
    model = models.efficientnet_b1(pretrained=False)
    model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, 10)

    # 체크포인트 로드
    checkpoint = torch.load(model_path, map_location='cpu')
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    class_names = checkpoint['class_names']

    return model, class_names


# 추론 함수
def predict_image(image_path, model, class_names):
    # 이미지 전처리
    transform = transforms.Compose([
        transforms.Resize((240, 240)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    image = Image.open(image_path).convert('RGB')
    image_tensor = transform(image).unsqueeze(0)

    # 추론
    with torch.no_grad():
        outputs = model(image_tensor)
        probabilities = torch.nn.functional.softmax(outputs, dim=1)
        confidence, predicted = torch.max(probabilities, 1)

    predicted_class = class_names[predicted.item()]
    confidence_score = confidence.item() * 100

    return predicted_class, confidence_score
