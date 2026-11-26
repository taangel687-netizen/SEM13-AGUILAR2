from django.contrib import admin

from .models import Autor, Libro, PerfilBiblioteca, Prestamo

admin.site.register([Autor, Libro, PerfilBiblioteca])
admin.site.register(Prestamo, list_display=["usuario", "libro", "fecha_devolucion", "estado"],
                    readonly_fields=["usuario", "libro", "fecha_prestamo", "fecha_devolucion", "devuelto_en"])

