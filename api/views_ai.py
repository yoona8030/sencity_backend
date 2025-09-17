# api/views_ai.py
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from .ai.predictor import predictor

class RecognizeAnimalView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.data.get("image")
        if not file:
            return Response({"detail": "image 필드가 필요합니다."}, status=400)
        try:
            img_bytes = file.read()
            topk = int(request.data.get("topk", 3))
            results = predictor.predict(img_bytes, topk=topk)
            return Response({"results": results}, status=200)
        except Exception as e:
            return Response({"detail": str(e)}, status=500)
