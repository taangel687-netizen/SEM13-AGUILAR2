from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django_filters import rest_framework as df
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import filters, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response

from config.api import BibliotecaAnon, BibliotecaUser, BurstRateThrottle, LibroPagination, PrestamoPagination, audit, in_group
from .models import Autor, Libro, PerfilBiblioteca, Prestamo

THROTTLES = [BibliotecaAnon, BibliotecaUser, BurstRateThrottle]
LIMITE_PRESTAMOS = 5


def bibliotecario(user):
    return user.is_staff or in_group(user, "bibliotecario")


def tiene_cupo(perfil):
    return perfil.prestamos.filter(devuelto_en__isnull=True).count() < LIMITE_PRESTAMOS


class GestionLibros(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return request.user.is_staff
        return bibliotecario(request.user)


class PuedeCrearPrestamo(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user.is_authenticated
        return bibliotecario(request.user)

    def validar_cupo(self, perfil):
        if not tiene_cupo(perfil):
            raise ValidationError({"usuario": "El usuario ya tiene cinco préstamos sin devolver."})


class AutorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Autor
        fields = ["id", "nombre", "nacionalidad", "biografia"]


class LibroSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="libro-detail")
    autor = AutorSerializer(read_only=True)
    autor_id = serializers.PrimaryKeyRelatedField(source="autor", queryset=Autor.objects.all(), write_only=True)
    disponible = serializers.SerializerMethodField()

    def get_disponible(self, obj) -> bool:
        return obj.stock > 0

    class Meta:
        model = Libro
        fields = ["id", "url", "isbn", "titulo", "autor", "autor_id", "editorial", "anio",
                  "categoria", "stock", "estante", "piso", "disponible"]


class FiltroLibro(df.FilterSet):
    anio__gte = df.NumberFilter(field_name="anio", lookup_expr="gte")
    disponible = df.BooleanFilter(method="filtrar_stock")

    def filtrar_stock(self, queryset, name, value):
        return queryset.filter(stock__gt=0) if value else queryset.filter(stock=0)

    class Meta:
        model = Libro
        fields = ["categoria"]


FiltroLibro.base_filters["año__gte"] = df.NumberFilter(field_name="anio", lookup_expr="gte")


class OrdenamientoLibro(filters.OrderingFilter):
    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        alias = {"año": "anio", "título": "titulo"}
        return [("-" if term.startswith("-") else "") + alias.get(term.lstrip("-"), term.lstrip("-"))
                for term in ordering]


class AutorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Autor.objects.order_by("id")
    serializer_class = AutorSerializer
    permission_classes = [GestionLibros]
    throttle_classes = THROTTLES


@extend_schema_view(create=extend_schema(examples=[OpenApiExample("Libro", value={
    "isbn": "9786120001111", "titulo": "Algoritmos", "autor_id": 1, "editorial": "UNCP",
    "anio": 2023, "categoria": "ingenieria", "stock": 8, "estante": "A-01", "piso": 2,
}, request_only=True)]))
class LibroViewSet(viewsets.ModelViewSet):
    queryset = Libro.objects.select_related("autor")
    serializer_class = LibroSerializer
    permission_classes = [GestionLibros]
    throttle_classes = THROTTLES
    pagination_class = LibroPagination
    filter_backends = [df.DjangoFilterBackend, filters.SearchFilter, OrdenamientoLibro]
    filterset_class = FiltroLibro
    search_fields = ["titulo", "autor__nombre"]
    ordering_fields = ["anio", "titulo", "año", "título"]
    ordering = ["id"]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise ValidationError("El libro tiene historial de préstamos.") from exc


class PrestamoSerializer(serializers.ModelSerializer):
    estado = serializers.ChoiceField(choices=Prestamo.Estado.choices, read_only=True)
    dias_restantes = serializers.IntegerField(read_only=True)
    multa = serializers.IntegerField(read_only=True)

    def validate_fecha_devolucion(self, value: date):
        if value < timezone.localdate():
            raise serializers.ValidationError("La fecha de devolución debe ser hoy o posterior.")
        return value

    class Meta:
        model = Prestamo
        fields = ["id", "usuario", "libro", "fecha_prestamo", "fecha_devolucion",
                  "devuelto_en", "estado", "dias_restantes", "multa"]
        read_only_fields = ["fecha_prestamo", "devuelto_en"]


@extend_schema_view(create=extend_schema(examples=[OpenApiExample(
    "Nuevo préstamo", value={"usuario": 1, "libro": 1, "fecha_devolucion": "2027-01-15"}, request_only=True,
)]))
class PrestamoViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Prestamo.objects.all()
    serializer_class = PrestamoSerializer
    permission_classes = [PuedeCrearPrestamo]
    throttle_classes = THROTTLES
    pagination_class = PrestamoPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or (self.action == "devolver" and bibliotecario(user)):
            return self.queryset
        return self.queryset.filter(usuario__usuario=user) if user.is_authenticated else self.queryset.none()

    @transaction.atomic
    def perform_create(self, serializer):
        perfil = PerfilBiblioteca.objects.select_for_update().get(pk=serializer.validated_data["usuario"].pk)
        libro = Libro.objects.select_for_update().get(pk=serializer.validated_data["libro"].pk)
        PuedeCrearPrestamo().validar_cupo(perfil)
        if libro.stock < 1:
            raise ValidationError({"libro": "El libro no tiene stock disponible."})
        prestamo = serializer.save(usuario=perfil, libro=libro)
        libro.stock -= 1
        libro.save(update_fields=["stock"])
        audit.info("prestamo creado id=%s operador=%s", prestamo.pk, self.request.user.pk)

    @extend_schema(request=None, responses=PrestamoSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def devolver(self, request, pk=None):
        prestamo = Prestamo.objects.select_for_update().get(pk=self.get_object().pk)
        if prestamo.devuelto_en is None:
            libro = Libro.objects.select_for_update().get(pk=prestamo.libro_id)
            libro.stock += 1
            libro.save(update_fields=["stock"])
            prestamo.devuelto_en = timezone.localdate()
            prestamo.save(update_fields=["devuelto_en"])
            audit.info("prestamo devuelto id=%s operador=%s", prestamo.pk, request.user.pk)
        return Response(self.get_serializer(prestamo).data)

    @extend_schema(responses=PrestamoSerializer(many=True))
    @action(detail=False, methods=["get"])
    def vencidos(self, request):
        queryset = self.get_queryset().filter(devuelto_en__isnull=True, fecha_devolucion__lt=timezone.localdate())
        return self.get_paginated_response(self.get_serializer(self.paginate_queryset(queryset), many=True).data)


class PerfilPublicoSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source="usuario.get_full_name", read_only=True)

    class Meta:
        model = PerfilBiblioteca
        fields = ["nombre", "tipo", "carrera"]


class PerfilSerializer(PerfilPublicoSerializer):
    email = serializers.EmailField(source="usuario.email", read_only=True)
    historial = PrestamoSerializer(source="prestamos", many=True, read_only=True)
    prestamos_activos = serializers.IntegerField(read_only=True)

    class Meta(PerfilPublicoSerializer.Meta):
        fields = ["id", *PerfilPublicoSerializer.Meta.fields, "email", "telefono", "historial", "prestamos_activos"]


class PerfilPermiso(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (view.action != "list" or request.user.is_staff)

    def has_object_permission(self, request, view, obj):
        return request.user.is_staff or obj.usuario_id == request.user.pk


class PerfilViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PerfilBiblioteca.objects.select_related("usuario").annotate(
        prestamos_activos=Count("prestamos", filter=Q(prestamos__devuelto_en__isnull=True)),
    ).order_by("id")
    serializer_class = PerfilSerializer
    permission_classes = [PerfilPermiso]
    throttle_classes = THROTTLES

    def get_serializer_class(self):
        return PerfilPublicoSerializer if self.action == "list" else PerfilSerializer

    def get_queryset(self):
        return self.queryset if self.action == "list" else self.queryset.prefetch_related("prestamos")

    @action(detail=False, methods=["get"])
    def perfil(self, request):
        from django.shortcuts import get_object_or_404
        perfil = get_object_or_404(self.get_queryset(), usuario=request.user)
        return Response(self.get_serializer(perfil).data)

