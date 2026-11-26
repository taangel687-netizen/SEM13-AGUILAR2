from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from biblioteca.models import Autor, Libro, PerfilBiblioteca, Prestamo
from tienda.models import Categoria, Cupon, Orden, Producto, Resena


class ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.ana = users.create_user("ana", password="Test13!", email="ana@example.test")
        cls.otro = users.create_user("otro")
        cls.admin = users.create_user("admin", is_staff=True)
        cls.biblio = users.create_user("bibliotecario")
        cls.vendedor = users.create_user("vendedor")
        cls.rival = users.create_user("rival")
        for rol, miembro in [("bibliotecario", cls.biblio), ("vendedor", cls.vendedor), ("vendedor", cls.rival)]:
            Group.objects.get_or_create(name=rol)[0].user_set.add(miembro)
        cls.perfil = PerfilBiblioteca.objects.create(usuario=cls.ana, tipo="estudiante", carrera="Sistemas")
        cls.otro_perfil = PerfilBiblioteca.objects.create(usuario=cls.otro, tipo="docente", carrera="Sistemas")
        cls.autor = Autor.objects.create(nombre="Ana Vargas", nacionalidad="Peruana")
        cls.libro = Libro.objects.create(isbn="9786120001111", titulo="Algoritmos", autor=cls.autor,
                                         editorial="UNCP", anio=2023, categoria="ingenieria", stock=6,
                                         estante="A1", piso=2)
        cls.categoria = Categoria.objects.create(slug="laptops", nombre="Laptops")
        cls.producto = Producto.objects.create(vendedor=cls.vendedor, sku="LAP-1", nombre="Laptop",
                                               descripcion="Ryzen 7", marca="dell", categoria=cls.categoria,
                                               precio=1000, descuento=10, stock=5)
        Cupon.objects.create(codigo="SEMANA13", porcentaje=10)

    def setUp(self):
        cache.clear()

    def login_as(self, user):
        self.client.force_authenticate(user)

    def post(self, path, data=None, code=200):
        response = self.client.post(path, data or {}, format="json")
        self.assertEqual(response.status_code, code, response.data)
        return response.data

    def test_token_expira_y_se_renueva(self):
        token = self.post("/api/token/", {"username": "ana", "password": "Test13!"})["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/usuarios/perfil/").data["email"], "ana@example.test")
        Token.objects.filter(key=token).update(created=timezone.now() - timedelta(days=2))
        self.assertEqual(self.client.get("/api/usuarios/perfil/").status_code, 401)
        self.assertNotEqual(token, self.post("/api/token/", {"username": "ana", "password": "Test13!"})["token"])

    def test_catalogo_libros_filtros_unicode_y_roles(self):
        url = "/api/libros/"
        data = self.client.get(url, {"categoria": "ingenieria", "año__gte": 2020,
                                     "disponible": "true", "search": "vargas", "ordering": "-año"}).data
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["autor"]["nombre"], "Ana Vargas")
        self.assertEqual(self.client.get(url, {"año__gte": 2024}).data["count"], 0)
        self.post(url, code=401)
        self.login_as(self.biblio)
        nuevo = self.post(url, {"isbn": "9786120001112", "titulo": "Redes", "autor_id": self.autor.pk,
                                "editorial": "UNCP", "anio": 2024, "categoria": "ingenieria",
                                "stock": 3, "estante": "A2", "piso": 2}, code=201)
        detalle = f"{url}{nuevo['id']}/"
        self.assertEqual(self.client.patch(detalle, {"stock": 5}, format="json").data["stock"], 5)
        self.assertEqual(self.client.delete(detalle).status_code, 403)
        self.login_as(self.admin)
        self.assertEqual(self.client.delete(detalle).status_code, 204)

    def test_prestamo_cupo_devolucion_y_privacidad(self):
        payload = {"usuario": self.perfil.pk, "libro": self.libro.pk,
                   "fecha_devolucion": timezone.localdate().isoformat()}
        self.login_as(self.biblio)
        for _ in range(5):
            creado = self.post("/api/prestamos/", payload, code=201)
        self.post("/api/prestamos/", payload, code=400)
        detalle = f"/api/prestamos/{creado['id']}/"
        self.assertEqual(self.client.get(detalle).status_code, 404)
        self.login_as(self.otro)
        self.assertEqual(self.client.get(detalle).status_code, 404)
        self.assertEqual(self.client.get(f"/api/usuarios/{self.perfil.pk}/").status_code, 403)
        self.post(f"{detalle}devolver/", code=403)
        self.login_as(self.ana)
        self.assertEqual(self.client.get(detalle).status_code, 200)
        self.assertEqual(self.client.get("/api/usuarios/perfil/").data["prestamos_activos"], 5)
        self.assertEqual(self.client.get("/api/usuarios/").status_code, 403)
        self.login_as(self.biblio)
        self.assertEqual(self.post(f"{detalle}devolver/")["estado"], "devuelto")
        self.post(f"{detalle}devolver/")
        self.libro.refresh_from_db()
        self.assertEqual(self.libro.stock, 2)
        self.libro.stock = 0
        self.libro.save(update_fields=["stock"])
        self.post("/api/prestamos/", payload, code=400)

    def test_vencidos_y_vista_publica_del_administrador(self):
        Prestamo.objects.create(usuario=self.perfil, libro=self.libro,
                                fecha_prestamo=timezone.localdate() - timedelta(days=10),
                                fecha_devolucion=timezone.localdate() - timedelta(days=3))
        self.login_as(self.admin)
        data = self.client.get("/api/prestamos/vencidos/?limit=1").data["results"][0]
        self.assertEqual((data["dias_restantes"], data["multa"], data["estado"]), (-3, 6, "vencido"))
        self.assertEqual(set(self.client.get("/api/usuarios/").data["results"][0]), {"nombre", "tipo", "carrera"})

    def test_producto_permisos_y_filtro(self):
        url = "/api/productos/"
        data = self.client.get(url, {"marca": "dell", "categoria": "laptops", "precio_min": 500,
                                     "precio_max": 2000, "disponible": "true", "search": "laptop Ryzen"}).data
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["precio_con_descuento"], "900.00")
        self.assertTrue(data["results"][0]["resenas"].endswith("/rese%C3%B1as/"))
        self.login_as(self.rival)
        detalle = f"{url}{self.producto.pk}/"
        self.assertEqual(self.client.patch(detalle, {"stock": 90}, format="json").status_code, 403)
        self.login_as(self.vendedor)
        producto = self.post(url, {"sku": "LAP-2", "nombre": "Laptop 2", "descripcion": "Equipo",
                                   "marca": "asus", "categoria_id": self.categoria.pk,
                                   "precio": "1860.00", "stock": 3}, code=201)
        self.assertIsNone(producto["rating_promedio"])
        self.assertEqual(self.client.patch(detalle, {"stock": 3}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(detalle).status_code, 403)

    def test_carrito_precio_cupon_checkout_y_cancelacion(self):
        self.login_as(self.ana)
        producto = {"producto": self.producto.pk}
        self.assertEqual(self.client.get("/api/carrito/").data["cantidad_items"], 0)
        self.post("/api/carrito/agregar/", producto | {"cantidad": 6}, code=400)
        self.post("/api/carrito/actualizar/", producto | {"cantidad": 1}, code=400)
        self.post("/api/carrito/agregar/", producto | {"cantidad": 1})
        self.post("/api/carrito/agregar/", producto | {"cantidad": 1})
        self.assertEqual(self.post("/api/carrito/actualizar/", producto | {"cantidad": 1})["cantidad_items"], 1)
        self.assertEqual(self.post("/api/carrito/eliminar/", producto)["cantidad_items"], 0)
        envio = {"direccion_envio": "Av. Real 100, Huancayo", "metodo_pago": "tarjeta"}
        self.post("/api/ordenes/", envio, code=400)
        self.post("/api/carrito/agregar/", producto | {"cantidad": 2})
        self.assertEqual(self.post("/api/carrito/cupon/", {"codigo": "semana13"})["total_con_descuento"], "1911.60")
        orden = self.post("/api/carrito/checkout/", envio, code=201)
        self.assertEqual((orden["estado"], orden["total"]), ("pendiente", "1911.60"))
        self.assertEqual(orden["items"][0]["precio_unitario"], "900.00")
        self.assertEqual(self.client.get("/api/carrito/").data["cantidad_items"], 0)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)
        self.producto.precio = 1200
        self.producto.save(update_fields=["precio"])
        detalle = f"/api/ordenes/{orden['id']}/"
        self.assertEqual(self.client.get(detalle).data["items"][0]["precio_unitario"], "900.00")
        self.assertEqual(self.client.get("/api/ordenes/mis-ordenes/").data["count"], 1)
        self.assertEqual(self.post(f"{detalle}cancelar/")["estado"], "cancelada")
        self.post(f"{detalle}cancelar/")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)

    def test_checkout_revalida_stock_y_conserva_carrito(self):
        self.login_as(self.ana)
        self.post("/api/carrito/agregar/", {"producto": self.producto.pk, "cantidad": 3})
        Producto.objects.filter(pk=self.producto.pk).update(stock=0)
        self.post("/api/ordenes/", {"direccion_envio": "Huancayo", "metodo_pago": "tarjeta"}, code=400)
        self.assertEqual(Orden.objects.count(), 0)
        self.assertEqual(self.client.get("/api/carrito/").data["cantidad_items"], 3)
        self.assertEqual(self.post("/api/carrito/vaciar/")["cantidad_items"], 0)

    def test_estados_tracking_y_resena_verificada(self):
        self.login_as(self.ana)
        resena = {"producto": self.producto.pk, "calificacion": 5, "titulo": "Excelente", "comentario": "Funciona"}
        self.post("/api/reseñas/", resena, code=403)
        self.post("/api/carrito/agregar/", {"producto": self.producto.pk, "cantidad": 1})
        orden = self.post("/api/ordenes/", {"direccion_envio": "Huancayo", "metodo_pago": "tarjeta"}, code=201)
        detalle = f"/api/ordenes/{orden['id']}/"
        self.login_as(self.otro)
        self.assertEqual(self.client.get(detalle).status_code, 404)
        self.login_as(self.rival)
        self.assertEqual(self.client.patch(detalle, {"estado": "pagada"}, format="json").status_code, 404)
        self.login_as(self.vendedor)
        self.assertEqual(self.client.patch(detalle, {"estado": "enviada"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(detalle, {"estado": "pagada"}, format="json").data["estado"], "pagada")
        envio = self.client.patch(detalle, {"estado": "enviada"}, format="json").data
        self.assertTrue(envio["numero_seguimiento"].startswith("TM-"))
        self.login_as(self.ana)
        self.post(f"{detalle}cancelar/", code=400)
        self.post("/api/reseñas/", resena | {"calificacion": 6}, code=400)
        creada = self.post("/api/reseñas/", resena, code=201)
        self.assertTrue(creada["es_compra_verificada"])
        self.post("/api/reseñas/", resena, code=400)
        self.login_as(self.otro)
        self.assertEqual(self.client.delete(f"/api/reseñas/{creada['id']}/").status_code, 403)
        self.login_as(None)
        self.assertEqual(self.client.get(f"/api/productos/{self.producto.pk}/reseñas/").data["count"], 1)
        self.assertEqual(self.client.get(f"/api/productos/{self.producto.pk}/").data["rating_promedio"], 5)
        self.login_as(self.ana)
        self.assertEqual(self.client.delete(f"/api/reseñas/{creada['id']}/").status_code, 204)
        self.assertFalse(Resena.objects.exists())

    def test_cors_documentacion_y_throttling(self):
        respuesta = self.client.options("/api/libros/", HTTP_ORIGIN="https://campus.uncp.edu.pe",
                                         HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
        self.assertEqual(respuesta.headers["Access-Control-Allow-Origin"], "https://campus.uncp.edu.pe")
        self.assertEqual(respuesta.headers["Access-Control-Allow-Credentials"], "true")
        respuesta = self.client.get("/api/productos/", HTTP_ORIGIN="https://origen.example")
        self.assertNotIn("Access-Control-Allow-Origin", respuesta.headers)
        for url in ("/api/schema/", "/api/docs/", "/api/redoc/"):
            self.assertEqual(self.client.get(url).status_code, 200)
        for _ in range(20):
            self.assertEqual(self.client.get("/api/libros/").status_code, 200)
        limitada = self.client.get("/api/libros/")
        self.assertEqual(limitada.status_code, 429)
        self.assertIn("Retry-After", limitada.headers)

    def test_checkout_comparte_limite_en_ambas_rutas(self):
        self.login_as(self.ana)
        for _ in range(5):
            self.post("/api/ordenes/", code=400)
            self.post("/api/carrito/checkout/", code=400)
        self.post("/api/ordenes/", code=429)

