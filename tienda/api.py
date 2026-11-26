from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as df
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response

from config.api import (
    CheckoutRateThrottle, IsOwnerOrReadOnly, OrdenPagination, ProductoPagination,
    SearchRateThrottle, TiendaAnon, TiendaUser, in_group,
)
from .models import Carrito, Categoria, Cupon, ItemCarrito, Orden, Producto, Resena
from .serializers import (
    CantidadCarritoInput, CarritoSerializer, CategoriaSerializer, CheckoutInput, CuponInput,
    EstadoOrdenInput, OrdenSerializer, ProductoCarritoInput, ProductoSerializer,
    ResenaSerializer, VendedorSerializer,
)
from .services import cambiar_estado, cancelar_orden, carrito_de, compro_producto, realizar_checkout

THROTTLES = [TiendaAnon, TiendaUser]
CHECKOUT = {"direccion_envio": "Av. Real 250, Huancayo", "metodo_pago": "transferencia"}


class PuedeVender(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return request.user.is_staff
        return request.user.is_staff or in_group(request.user, "vendedor")

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or request.user.is_staff or obj.vendedor_id == request.user.pk


class FiltroProducto(df.FilterSet):
    categoria = df.CharFilter(field_name="categoria__slug")
    precio_min = df.NumberFilter(field_name="precio", lookup_expr="gte")
    precio_max = df.NumberFilter(field_name="precio", lookup_expr="lte")
    disponible = df.BooleanFilter(method="por_stock")

    def por_stock(self, queryset, name, value):
        return queryset.filter(stock__gt=0) if value else queryset.filter(stock=0)

    class Meta:
        model = Producto
        fields = ["marca"]


class CategoriaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Categoria.objects.order_by("id")
    serializer_class = CategoriaSerializer
    permission_classes = [AllowAny]
    throttle_classes = THROTTLES


class VendedorViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = get_user_model().objects.filter(productos__isnull=False).distinct()
    serializer_class = VendedorSerializer
    permission_classes = [AllowAny]
    throttle_classes = THROTTLES


@extend_schema_view(create=extend_schema(examples=[OpenApiExample("Producto", value={
    "sku": "LAP-999", "nombre": "Laptop Ryzen 7", "descripcion": "Equipo de 16 GB",
    "marca": "lenovo", "categoria_id": 1, "precio": "1899.00", "descuento": 10,
    "stock": 5, "imagenes": [], "especificaciones": {"ram_gb": 16},
}, request_only=True)]))
class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.select_related("categoria", "vendedor").annotate(
        rating_promedio=Avg("resenas__calificacion"),
    )
    serializer_class = ProductoSerializer
    permission_classes = [PuedeVender]
    throttle_classes = [*THROTTLES, SearchRateThrottle]
    pagination_class = ProductoPagination
    filter_backends = [df.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = FiltroProducto
    search_fields = ["nombre", "descripcion", "marca", "sku"]
    ordering_fields = ["precio", "rating_promedio", "fecha_creacion"]
    ordering = ["id"]

    def perform_create(self, serializer):
        serializer.save(vendedor=self.request.user)
        serializer.instance.rating_promedio = None

    @extend_schema(responses=ResenaSerializer(many=True), filters=False)
    @action(detail=True, methods=["get"], url_path="reseñas")
    def resenas(self, request, pk=None):
        queryset = self.get_object().resenas.select_related("usuario")
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(ResenaSerializer(page, many=True).data)


class CarritoViewSet(viewsets.GenericViewSet):
    queryset = Carrito.objects.all()
    serializer_class = CarritoSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = THROTTLES

    def respuesta(self, carrito):
        carrito = self.queryset.select_related("cupon").prefetch_related("items__producto").get(pk=carrito.pk)
        return Response(self.get_serializer(carrito).data)

    def list(self, request):
        return self.respuesta(carrito_de(request.user))

    def cambiar_item(self, request, *, sumar):
        datos = CantidadCarritoInput(data=request.data)
        datos.is_valid(raise_exception=True)
        carrito = carrito_de(request.user, bloquear=True)
        producto = get_object_or_404(Producto.objects.select_for_update(), pk=datos.validated_data["producto"])
        cantidad = datos.validated_data["cantidad"]
        if sumar:
            anterior = carrito.items.filter(producto=producto).values_list("cantidad", flat=True).first()
            cantidad += anterior or 0
        elif not carrito.items.filter(producto=producto).exists():
            raise ValidationError({"producto": "El producto no está en el carrito."})
        if cantidad > producto.stock:
            raise ValidationError({"cantidad": f"Stock disponible: {producto.stock}."})
        ItemCarrito.objects.update_or_create(carrito=carrito, producto=producto, defaults={"cantidad": cantidad})
        return self.respuesta(carrito)

    @extend_schema(request=CantidadCarritoInput, responses=CarritoSerializer)
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def agregar(self, request):
        return self.cambiar_item(request, sumar=True)

    @extend_schema(request=CantidadCarritoInput, responses=CarritoSerializer)
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def actualizar(self, request):
        return self.cambiar_item(request, sumar=False)

    @extend_schema(request=ProductoCarritoInput, responses=CarritoSerializer)
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def eliminar(self, request):
        datos = ProductoCarritoInput(data=request.data)
        datos.is_valid(raise_exception=True)
        carrito = carrito_de(request.user, bloquear=True)
        carrito.items.filter(producto_id=datos.validated_data["producto"]).delete()
        return self.respuesta(carrito)

    @extend_schema(request=None, responses=CarritoSerializer)
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def vaciar(self, request):
        carrito = carrito_de(request.user, bloquear=True)
        carrito.items.all().delete()
        carrito.cupon = None
        carrito.save(update_fields=["cupon"])
        return self.respuesta(carrito)

    @extend_schema(request=CuponInput, responses=CarritoSerializer)
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def cupon(self, request):
        datos = CuponInput(data=request.data)
        datos.is_valid(raise_exception=True)
        carrito = carrito_de(request.user, bloquear=True)
        codigo = datos.validated_data["codigo"].upper()
        carrito.cupon = get_object_or_404(Cupon, codigo=codigo, activo=True) if codigo else None
        carrito.save(update_fields=["cupon"])
        return self.respuesta(carrito)

    @extend_schema(request=CheckoutInput, responses={201: OrdenSerializer},
                   examples=[OpenApiExample("Envío", value=CHECKOUT, request_only=True)])
    @action(detail=False, methods=["post"], throttle_classes=[*THROTTLES, CheckoutRateThrottle])
    def checkout(self, request):
        return respuesta_checkout(request)


def respuesta_checkout(request):
    datos = CheckoutInput(data=request.data)
    datos.is_valid(raise_exception=True)
    orden = realizar_checkout(request.user, datos.validated_data)
    return Response(OrdenSerializer(orden).data, status=status.HTTP_201_CREATED)


class OrdenViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Orden.objects.prefetch_related("items")
    serializer_class = OrdenSerializer
    pagination_class = OrdenPagination
    throttle_classes = THROTTLES

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return self.queryset.none()
        if self.action == "partial_update" and not user.is_staff:
            return self.queryset.filter(items__vendedor=user).distinct()
        if not user.is_staff or self.action == "mis_ordenes":
            return self.queryset.filter(usuario=user)
        return self.queryset

    def get_throttles(self):
        if self.action == "create":
            return [*(cls() for cls in THROTTLES), CheckoutRateThrottle()]
        return super().get_throttles()

    @extend_schema(request=CheckoutInput, responses={201: OrdenSerializer},
                   examples=[OpenApiExample("Envío", value=CHECKOUT, request_only=True)])
    def create(self, request):
        return respuesta_checkout(request)

    @extend_schema(request=EstadoOrdenInput, responses=OrdenSerializer)
    @transaction.atomic
    def partial_update(self, request, pk=None):
        if not request.user.is_staff and not in_group(request.user, "vendedor"):
            raise PermissionDenied()
        datos = EstadoOrdenInput(data=request.data)
        datos.is_valid(raise_exception=True)
        orden = Orden.objects.select_for_update().get(pk=self.get_object().pk)
        if not request.user.is_staff and orden.items.exclude(vendedor=request.user).exists():
            raise PermissionDenied("Las órdenes con varios vendedores requieren gestión administrativa.")
        cambiar_estado(orden, datos.validated_data["estado"], request.user)
        return Response(self.get_serializer(orden).data)

    @extend_schema(request=None, responses=OrdenSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancelar(self, request, pk=None):
        orden = Orden.objects.select_for_update().get(pk=self.get_object().pk)
        cancelar_orden(orden, request.user)
        return Response(self.get_serializer(orden).data)

    @extend_schema(responses=OrdenSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="mis-ordenes")
    def mis_ordenes(self, request):
        return self.list(request)


class EsCompradorVerificado(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or request.user.is_authenticated

    def validar_compra(self, usuario, producto):
        if not compro_producto(usuario, producto):
            raise PermissionDenied("Solo se pueden reseñar productos comprados con pago confirmado.")


class ResenaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = Resena.objects.select_related("usuario")
    serializer_class = ResenaSerializer
    permission_classes = [EsCompradorVerificado, IsOwnerOrReadOnly]
    throttle_classes = THROTTLES

    @transaction.atomic
    def perform_create(self, serializer):
        usuario = self.request.user
        producto = serializer.validated_data["producto"]
        EsCompradorVerificado().validar_compra(usuario, producto)
        if self.queryset.filter(usuario=usuario, producto=producto).exists():
            raise ValidationError({"producto": "Ya existe una reseña para este producto."})
        serializer.save(usuario=usuario)



