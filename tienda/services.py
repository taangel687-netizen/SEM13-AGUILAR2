from uuid import uuid4

from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import ValidationError

from config.api import audit
from .models import Carrito, ItemOrden, Orden, Producto
from .serializers import calcular_totales

CONFIRMADAS = [Orden.Estado.PAGADA, Orden.Estado.ENVIADA, Orden.Estado.ENTREGADA]
TRANSICIONES = {
    Orden.Estado.PENDIENTE: Orden.Estado.PAGADA,
    Orden.Estado.PAGADA: Orden.Estado.ENVIADA,
    Orden.Estado.ENVIADA: Orden.Estado.ENTREGADA,
}


def compro_producto(usuario, producto):
    return ItemOrden.objects.filter(
        orden__usuario=usuario, producto=producto, orden__estado__in=CONFIRMADAS,
    ).exists()


def carrito_de(usuario, *, bloquear=False):
    queryset = Carrito.objects
    if bloquear:
        queryset = queryset.select_for_update()
    carrito, _ = queryset.get_or_create(usuario=usuario)
    return carrito


@transaction.atomic
def realizar_checkout(usuario, datos):
    carrito = carrito_de(usuario, bloquear=True)
    items = list(carrito.items.all().order_by("producto_id"))
    if not items:
        raise ValidationError({"carrito": "El carrito está vacío."})
    productos = Producto.objects.select_for_update().in_bulk(item.producto_id for item in items)
    for item in items:
        item.producto = productos[item.producto_id]
        if item.cantidad > item.producto.stock:
            raise ValidationError({"stock": f"Stock insuficiente para {item.producto.sku}."})
    total = calcular_totales(items, carrito.cupon)["total_con_descuento"]
    orden = Orden.objects.create(usuario=usuario, total=total, **datos)
    ItemOrden.objects.bulk_create([
        ItemOrden(orden=orden, producto=item.producto, vendedor_id=item.producto.vendedor_id,
                  sku=item.producto.sku, nombre=item.producto.nombre,
                  precio_unitario=item.producto.precio_con_descuento, cantidad=item.cantidad)
        for item in items
    ])
    for item in items:
        Producto.objects.filter(pk=item.producto_id).update(stock=F("stock") - item.cantidad)
    carrito.items.all().delete()
    carrito.cupon = None
    carrito.save(update_fields=["cupon"])
    audit.info("orden creada id=%s usuario=%s", orden.pk, usuario.pk)
    return orden


def cambiar_estado(orden, estado, operador):
    if estado != TRANSICIONES.get(orden.estado):
        raise ValidationError({"estado": f"Transición inválida desde {orden.estado}."})
    orden.estado = estado
    if estado == Orden.Estado.ENVIADA:
        orden.numero_seguimiento = f"TM-{uuid4().hex[:12].upper()}"
    orden.save(update_fields=["estado", "numero_seguimiento"])
    audit.info("orden actualizada id=%s estado=%s operador=%s", orden.pk, estado, operador.pk)


def cancelar_orden(orden, operador):
    if orden.estado == Orden.Estado.CANCELADA:
        return
    if orden.estado != Orden.Estado.PENDIENTE:
        raise ValidationError({"estado": "Solo se pueden cancelar órdenes pendientes."})
    for item in orden.items.order_by("producto_id"):
        Producto.objects.filter(pk=item.producto_id).update(stock=F("stock") + item.cantidad)
    orden.estado = Orden.Estado.CANCELADA
    orden.save(update_fields=["estado"])
    audit.info("orden cancelada id=%s operador=%s", orden.pk, operador.pk)

