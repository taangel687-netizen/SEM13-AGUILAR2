from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Carrito, Categoria, IGV, ItemCarrito, ItemOrden, MONEDA, Orden, Producto, Resena


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "slug", "nombre", "descripcion", "imagen"]


class VendedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "username"]


class ProductoSerializer(serializers.ModelSerializer):
    categoria = CategoriaSerializer(read_only=True)
    categoria_id = serializers.PrimaryKeyRelatedField(
        source="categoria", queryset=Categoria.objects.all(), write_only=True,
    )
    vendedor = serializers.HyperlinkedRelatedField(read_only=True, view_name="vendedor-detail")
    resenas = serializers.HyperlinkedIdentityField(view_name="producto-resenas")
    precio_con_descuento = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    rating_promedio = serializers.FloatField(read_only=True, allow_null=True)
    disponible = serializers.SerializerMethodField()
    imagenes = serializers.ListField(child=serializers.URLField(), required=False)
    especificaciones = serializers.DictField(required=False)

    def get_disponible(self, obj) -> bool:
        return obj.stock > 0

    class Meta:
        model = Producto
        fields = ["id", "sku", "nombre", "descripcion", "marca", "categoria", "categoria_id", "precio",
                  "descuento", "stock", "imagenes", "especificaciones", "vendedor", "resenas",
                  "precio_con_descuento", "rating_promedio", "disponible", "fecha_creacion"]


class ItemCarritoSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="producto.sku", read_only=True)
    nombre = serializers.CharField(source="producto.nombre", read_only=True)
    precio_unitario = serializers.DecimalField(
        source="producto.precio_con_descuento", max_digits=12, decimal_places=2, read_only=True,
    )

    class Meta:
        model = ItemCarrito
        fields = ["producto", "sku", "nombre", "cantidad", "precio_unitario"]


def calcular_totales(items, cupon):
    subtotal = sum((item.producto.precio_con_descuento * item.cantidad for item in items), Decimal("0.00"))
    impuesto = (subtotal * IGV).quantize(MONEDA)
    total = subtotal + impuesto
    porcentaje = cupon.porcentaje if cupon and cupon.activo else 0
    base_descuento = (subtotal * (100 - porcentaje) / 100).quantize(MONEDA)
    total_descuento = base_descuento + (base_descuento * IGV).quantize(MONEDA)
    return {
        "subtotal": str(subtotal), "impuestos": str(impuesto), "total": str(total),
        "total_con_descuento": str(total_descuento),
        "cantidad_items": sum(item.cantidad for item in items),
    }


class CarritoSerializer(serializers.ModelSerializer):
    items = ItemCarritoSerializer(many=True, read_only=True)
    cupon = serializers.SlugRelatedField(slug_field="codigo", read_only=True)
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    impuestos = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    total_con_descuento = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    cantidad_items = serializers.IntegerField(read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update(calcular_totales(list(instance.items.all()), instance.cupon))
        return data

    class Meta:
        model = Carrito
        fields = ["id", "usuario", "items", "cupon", "subtotal", "impuestos", "total",
                  "total_con_descuento", "cantidad_items"]


class ProductoCarritoInput(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)


class CantidadCarritoInput(ProductoCarritoInput):
    cantidad = serializers.IntegerField(min_value=1, max_value=2147483647)


class CuponInput(serializers.Serializer):
    codigo = serializers.CharField(max_length=30, allow_blank=True)


class CheckoutInput(serializers.ModelSerializer):
    class Meta:
        model = Orden
        fields = ["direccion_envio", "metodo_pago"]


class EstadoOrdenInput(serializers.Serializer):
    estado = serializers.ChoiceField(choices=Orden.Estado.choices)


class ItemOrdenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemOrden
        fields = ["producto", "sku", "nombre", "precio_unitario", "cantidad"]


class OrdenSerializer(serializers.ModelSerializer):
    items = ItemOrdenSerializer(many=True, read_only=True)
    tiempo_estimado_entrega = serializers.SerializerMethodField()

    def get_tiempo_estimado_entrega(self, obj) -> dict[str, str]:
        inicio = obj.fecha_creacion + timedelta(days=3)
        fin = obj.fecha_creacion + timedelta(days=5)
        return {"desde": inicio.date().isoformat(), "hasta": fin.date().isoformat()}

    class Meta:
        model = Orden
        fields = ["id", "usuario", "items", "direccion_envio", "metodo_pago", "estado", "total",
                  "fecha_creacion", "numero_seguimiento", "tiempo_estimado_entrega"]
        read_only_fields = fields


class ResenaSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source="usuario.username", read_only=True)
    es_compra_verificada = serializers.BooleanField(default=True, read_only=True)

    class Meta:
        model = Resena
        fields = ["id", "usuario", "producto", "calificacion", "titulo", "comentario",
                  "fecha_creacion", "es_compra_verificada"]

