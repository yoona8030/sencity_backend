from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from api.metrics.models import Event

class LoggingTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        resp = super().post(request, *args, **kwargs)
        if resp.status_code == 200:
            User = get_user_model()
            user = User.objects.filter(username=request.data.get("username")).first()
            Event.objects.create(user=user, event_type=Event.Types.LOGIN, meta={"source": "jwt"})
        return resp
