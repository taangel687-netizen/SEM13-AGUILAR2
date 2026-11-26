from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from biblioteca.api import AutorViewSet, LibroViewSet, PerfilViewSet, PrestamoViewSet
from tienda.api import CarritoViewSet, CategoriaViewSet, OrdenViewSet, ProductoViewSet, ResenaViewSet, VendedorViewSet
from .token import TokenView

router = DefaultRouter()
router.register("autores", AutorViewSet)
router.register("libros", LibroViewSet)
router.register("prestamos", PrestamoViewSet)
router.register("usuarios", PerfilViewSet)
router.register("categorias", CategoriaViewSet)
router.register("vendedores", VendedorViewSet, basename="vendedor")
router.register("productos", ProductoViewSet)
router.register("carrito", CarritoViewSet, basename="carrito")
router.register("ordenes", OrdenViewSet)
router.register("reseñas", ResenaViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", TokenView.as_view(), name="token"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]


