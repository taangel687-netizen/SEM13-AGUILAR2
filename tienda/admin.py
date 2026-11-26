from django.contrib import admin

from .models import Categoria, Cupon, Orden, Producto, Resena

admin.site.register([Categoria, Cupon, Producto, Resena])
admin.site.register(Orden, list_display=["id", "usuario", "estado", "total"],
                    readonly_fields=["usuario", "direccion_envio", "metodo_pago", "estado", "total", "numero_seguimiento"])

