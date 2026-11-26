from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


MONEDA = Decimal("0.01")
IGV = Decimal("0.18")


class Categoria(models.Model):
    slug = models.SlugField(unique=True)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    imagen = models.URLField(blank=True)


class Producto(models.Model):
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="productos")
    sku = models.CharField(max_length=40, unique=True)
    nombre = models.CharField(max_length=180, db_index=True)
    descripcion = models.TextField()
    marca = models.SlugField(db_index=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    precio = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(MONEDA)])
    descuento = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    stock = models.PositiveIntegerField(default=0)
    imagenes = models.JSONField(default=list, blank=True)
    especificaciones = models.JSONField(default=dict, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    @property
    def precio_con_descuento(self):
        return (self.precio * (100 - self.descuento) / 100).quantize(MONEDA)




class Cupon(models.Model):
    codigo = models.CharField(max_length=30, unique=True)
    porcentaje = models.PositiveSmallIntegerField(validators=[MaxValueValidator(100)])
    activo = models.BooleanField(default=True)


class Carrito(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="carrito")
    cupon = models.ForeignKey(Cupon, on_delete=models.SET_NULL, null=True, blank=True)


class ItemCarrito(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["carrito", "producto"], name="carrito_producto_unico"),
                       models.CheckConstraint(condition=Q(cantidad__gte=1), name="carrito_cantidad_positiva")]


class Orden(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        PAGADA = "pagada", "Pagada"
        ENVIADA = "enviada", "Enviada"
        ENTREGADA = "entregada", "Entregada"
        CANCELADA = "cancelada", "Cancelada"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes")
    direccion_envio = models.CharField(max_length=250)
    metodo_pago = models.CharField(max_length=20, choices=[
        ("tarjeta", "Tarjeta"), ("transferencia", "Transferencia"), ("contraentrega", "Contraentrega"),
    ])
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    numero_seguimiento = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-id"]


class ItemOrden(models.Model):
    orden = models.ForeignKey(Orden, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.SET_NULL, null=True)
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventas")
    sku = models.CharField(max_length=40)
    nombre = models.CharField(max_length=180)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad = models.PositiveIntegerField()


class Resena(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resenas")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="resenas")
    calificacion = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    titulo = models.CharField(max_length=120)
    comentario = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["usuario", "producto"], name="resena_unica"),
                       models.CheckConstraint(condition=Q(calificacion__range=(1, 5)), name="resena_rango")]


