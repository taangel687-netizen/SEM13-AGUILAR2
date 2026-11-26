from datetime import timedelta
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed, Throttled
from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

audit = logging.getLogger("api.audit")
TOKEN_LIFETIME = timedelta(hours=24)


def in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created + TOKEN_LIFETIME <= timezone.now():
            raise AuthenticationFailed("Token expirado. Solicite uno nuevo.")
        return user, token


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or request.user.is_staff or request.user.pk == obj.usuario_id


class BibliotecaAnon(AnonRateThrottle):
    scope = "bib_anon"


class BibliotecaUser(UserRateThrottle):
    scope = "bib_user"


class BurstRateThrottle(UserRateThrottle):
    scope = "bib_burst"


class TiendaAnon(AnonRateThrottle):
    scope = "shop_anon"


class TiendaUser(UserRateThrottle):
    scope = "shop_user"


class CheckoutRateThrottle(UserRateThrottle):
    scope = "checkout"


class SearchRateThrottle(UserRateThrottle):
    scope = "search"

    def allow_request(self, request, view):
        return not request.query_params.get("search") or super().allow_request(request, view)


class LibroPagination(PageNumberPagination):
    page_size = 20


class ProductoPagination(PageNumberPagination):
    page_size = 24


class PrestamoPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class OrdenPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


def log_throttling(exc, context):
    if isinstance(exc, Throttled):
        request = context["request"]
        audit.warning("throttled path=%s method=%s user=%s", request.path, request.method, request.user.pk)
    from rest_framework.views import exception_handler
    return exception_handler(exc, context)


