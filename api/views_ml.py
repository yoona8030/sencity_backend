# api/views_ml.py
from __future__ import annotations
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from PIL import Image
from io import BytesIO

from .ml import predict_topk_grouped

# 그룹 키 → EN 라벨 (프론트 표준 표시용)
GROUP_DISPLAY_EN = {
    "deer": "Deer",            # 고라니/노루 → Deer로 표기
    "heron_egret": "Heron/Egret", # 왜가리/중대백로
    "sciuridae": "Squirrel",   # 다람쥐/청설모 → Squirrel
}

@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def recognize_animal_grouped(request):
    """
    입력: multipart/form-data, 키명: 'photo' (백업 키로 'image'도 허용)
    출력: { label, label_ko, prob, group, members }
    """
    # 1) 파일 꺼내기 (photo 우선, image 백업)
    file = request.FILES.get("photo") or request.FILES.get("image")
    if not file:
        return Response({"detail": "photo 파일이 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

    # 2) 이미지 열기
    try:
        img = Image.open(BytesIO(file.read()))
    except Exception:
        return Response({"detail": "이미지 열기 실패"}, status=status.HTTP_400_BAD_REQUEST)

    # 3) 그룹 TopK
    results = predict_topk_grouped(img, k=3) or []
    if not results:
        return Response({"label": "-"}, status=status.HTTP_200_OK)

    top = results[0]
    group_key = top.get("group") or ""
    label_ko  = top.get("label_ko")  # 그룹이 아닌 단일종이면 None일 수 있음
    members   = top.get("members") or []

    # 4) 최종 EN 라벨 결정(그룹이면 그룹 디스플레이, 단일종이면 맴버 1위 라벨)
    label_en = GROUP_DISPLAY_EN.get(group_key)
    if not label_en:
        label_en = (members[0][0] if members else group_key) or "-"

    # 5) 응답
    return Response({
        "label": label_en,          # EN: Deer / Squirrel / Heron/Egret / (단일종이면 원라벨)
        "label_ko": label_ko,       # KO: 고라니/노루 / 다람쥐/청설모 / 왜가리/중대백로
        "prob": float(top.get("prob", 0.0)),
        "group": group_key,
        "members": members,         # 예: [("goat", 0.72), ("roe deer", 0.13)]
    }, status=status.HTTP_200_OK)
