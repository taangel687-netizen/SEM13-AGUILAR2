"""Carga idempotente de datos ficticios para los dos casos."""
import argparse
import os
from datetime import timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from biblioteca.models import Autor, Libro, PerfilBiblioteca, Prestamo
from tienda.models import Categoria, Cupon, ItemOrden, Orden, Producto, Resena

NOMBRES = ["Lucía", "Mateo", "Sofía", "Diego", "Valeria", "Bruno", "Camila", "Gabriel", "Elena", "Joaquín"]
APELLIDOS = ["Quispe", "Rojas", "Huamán", "Paredes", "Salazar", "Soto", "Vargas", "Campos", "León", "Mendoza"]
LIBROS = [
    ("Algoritmos y estructuras de datos", "ingenieria", "Rosa Vargas"),
    ("Fundamentos de bases de datos", "ingenieria", "Luis Chávez"),
    ("Redes y protocolos de Internet", "ingenieria", "Ana Salazar"),
    ("Estadística aplicada", "ciencias", "Inés Flores"),
    ("Historia del valle del Mantaro", "humanidades", "José Quispe"),
]
CATALOGO = [
    ("laptops", "Laptops", "Laptop", ["lenovo", "dell", "asus", "hp"], 1350, {"ram_gb": 16, "ssd_gb": 512}),
    ("smartphones", "Smartphones", "Smartphone", ["samsung", "motorola", "xiaomi"], 620, {"almacenamiento_gb": 128}),
    ("componentes", "Componentes", "SSD NVMe", ["kingston", "crucial", "wd"], 180, {"capacidad_gb": 1024}),
    ("accesorios", "Accesorios", "Teclado mecánico", ["logitech", "hyperx", "razer"], 115, {"conexion": "USB"}),
]


def cuenta(username, contrasena, nombre="", apellido="", admin=False):
    return get_user_model().objects.get_or_create(username=username, defaults={
        "password": make_password(contrasena), "first_name": nombre, "last_name": apellido,
        "email": f"{username}@example.test", "is_staff": admin, "is_superuser": admin,
    })[0]


@transaction.atomic
def cargar(contrasena):
    hoy = timezone.localdate()
    cuenta("demo_admin", contrasena, admin=True)
    for rol in ("bibliotecario", "vendedor"):
        grupo, _ = Group.objects.get_or_create(name=rol)
        operadores = [cuenta(f"demo_{rol}", contrasena)]
        if rol == "vendedor":
            operadores.append(cuenta("demo_vendedor2", contrasena))
            vendedores = operadores
        grupo.user_set.add(*operadores)

    clientes = [
        cuenta(f"demo_cliente{i + 1:02}", contrasena, NOMBRES[i % 10], APELLIDOS[(i + i // 10) % 10])
        for i in range(20)
    ]
    perfiles = [
        PerfilBiblioteca.objects.get_or_create(usuario=usuario, defaults={
            "tipo": "docente" if i % 4 == 0 else "estudiante",
            "carrera": "Ingeniería de Sistemas" if i % 2 == 0 else "Ingeniería Eléctrica",
        })[0] for i, usuario in enumerate(clientes[:10])
    ]
    libros = []
    for i in range(50):
        titulo, categoria, nombre = LIBROS[i % len(LIBROS)]
        autor, _ = Autor.objects.get_or_create(nombre=nombre, defaults={
            "nacionalidad": "Peruana", "biografia": f"Autoría de textos universitarios en {categoria}.",
        })
        libro, _ = Libro.objects.get_or_create(isbn=f"978612130{i:04}", defaults={
            "titulo": f"{titulo}, edición {i // len(LIBROS) + 1}", "autor": autor,
            "editorial": "Fondo Editorial Universitario", "anio": 2016 + i % 11,
            "categoria": categoria, "stock": 0 if i == 49 else 4 + i % 7,
            "estante": f"{categoria[0].upper()}-{i % 12 + 1:02}", "piso": 1 + i % 3,
        })
        libros.append(libro)
    for i, perfil in enumerate(perfiles):
        for j in range(3):
            inicio = hoy - timedelta(days=20 - j * 4)
            vence = hoy + timedelta(days=(-7, -1, 8)[j])
            libro = libros[i * 3 + j]
            devuelto = hoy - timedelta(days=2) if j == 0 else None
            _, creado = Prestamo.objects.get_or_create(usuario=perfil, libro=libro, defaults={
                "fecha_prestamo": inicio, "fecha_devolucion": vence, "devuelto_en": devuelto,
            })
            if creado and devuelto is None and libro.stock:
                libro.stock -= 1
                libro.save(update_fields=["stock"])

    productos = []
    for i in range(100):
        slug, nombre, familia, marcas, base, spec = CATALOGO[i % len(CATALOGO)]
        categoria, _ = Categoria.objects.get_or_create(slug=slug, defaults={
            "nombre": nombre, "descripcion": f"Catálogo TecnoMarket de {nombre.lower()}.",
        })
        marca = marcas[(i // 4) % len(marcas)]
        producto, _ = Producto.objects.get_or_create(sku=f"TM-{i + 1:04}", defaults={
            "vendedor": vendedores[i % 2], "nombre": f"{familia} {marca.title()} Serie {100 + i}",
            "descripcion": f"{familia} para estudio, trabajo y uso diario.",
            "marca": marca, "categoria": categoria, "precio": Decimal(base + 25 * (i % 21)),
            "descuento": 10 if i % 8 == 0 else 0, "stock": 0 if i % 17 == 16 else 8 + i % 25,
            "especificaciones": spec,
        })
        productos.append(producto)
    Cupon.objects.get_or_create(codigo="SEMANA13", defaults={"porcentaje": 10})
    for i in range(50):
        usuario = clientes[i % len(clientes)]
        seleccion = productos[2*i:2*i+2]
        subtotal = sum(p.precio_con_descuento for p in seleccion)
        direccion = f"Jr. Los Álamos {100 + i}, Huancayo"
        orden, creada = Orden.objects.get_or_create(usuario=usuario, direccion_envio=direccion, defaults={
            "estado": Orden.Estado.ENTREGADA, "metodo_pago": "transferencia",
            "total": (subtotal * Decimal("1.18")).quantize(Decimal("0.01")),
            "numero_seguimiento": f"TM-DEMO-{i + 1:04}",
        })
        for producto in seleccion:
            if creada:
                ItemOrden.objects.create(
                    orden=orden, producto=producto, vendedor=producto.vendedor, sku=producto.sku,
                    nombre=producto.nombre, precio_unitario=producto.precio_con_descuento, cantidad=1,
                )
            Resena.objects.get_or_create(usuario=usuario, producto=producto, defaults={
                "calificacion": 3 + producto.pk % 3, "titulo": "Compra recibida",
                "comentario": "El producto llegó completo y coincide con las especificaciones.",
            })
    for nombre, consulta in (
        ("libros", Libro.objects.filter(isbn__startswith="978612130")),
        ("perfiles", PerfilBiblioteca.objects.filter(usuario__in=clientes[:10])),
        ("préstamos", Prestamo.objects.filter(usuario__in=perfiles, libro__in=libros)),
        ("clientes", get_user_model().objects.filter(pk__in=[u.pk for u in clientes])),
        ("productos", Producto.objects.filter(pk__in=[p.pk for p in productos])),
        ("órdenes", Orden.objects.filter(numero_seguimiento__startswith="TM-DEMO-")),
        ("reseñas", Resena.objects.filter(usuario__in=clientes, producto__in=productos)),
    ):
        print(f"{nombre}: {consulta.count()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", default="PracticaLocal13!")
    args = parser.parse_args()
    if not settings.DEBUG:
        parser.error("La carga de demostración solo se ejecuta con DJANGO_DEBUG=1.")
    cargar(args.password)

