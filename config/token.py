from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response

from .api import LoginThrottle, TOKEN_LIFETIME

class TokenView(ObtainAuthToken):
    throttle_classes = [LoginThrottle]
    authentication_classes = []

    @extend_schema(request=ObtainAuthToken.serializer_class, responses=inline_serializer(
        name="TokenRespuesta", fields={"token": serializers.CharField(), "expira": serializers.DateTimeField()},
    ))
    @transaction.atomic
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = get_user_model().objects.select_for_update().get(pk=serializer.validated_data["user"].pk)
        token, _ = Token.objects.get_or_create(user=user)
        if token.created + TOKEN_LIFETIME <= timezone.now():
            token.delete()
            token = Token.objects.create(user=user)
        return Response({"token": token.key, "expira": token.created + TOKEN_LIFETIME})



