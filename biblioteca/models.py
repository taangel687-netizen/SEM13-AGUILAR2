from django.conf import settings
from django.db import models
from django.utils import timezone


class Autor(models.Model):
    nombre = models.CharField(max_length=150)
    nacionalidad = models.CharField(max_length=100)
    biografia = models.TextField(blank=True)

    def __str__(self):
        return self.nombre


class Libro(models.Model):
    isbn = models.CharField(max_length=17, unique=True)
    titulo = models.CharField(max_length=200, db_index=True)
    autor = models.ForeignKey(Autor, on_delete=models.PROTECT, related_name="libros")
    editorial = models.CharField(max_length=120)
    anio = models.PositiveSmallIntegerField(db_index=True)
    categoria = models.SlugField(db_index=True)
    stock = models.PositiveIntegerField(default=0)
    estante = models.CharField(max_length=30)
    piso = models.PositiveSmallIntegerField()
    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.titulo


class PerfilBiblioteca(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_biblioteca")
    tipo = models.CharField(max_length=12, choices=[("estudiante", "Estudiante"), ("docente", "Docente")])
    carrera = models.CharField(max_length=120)
    telefono = models.CharField(max_length=25, blank=True)


class Prestamo(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "activo", "Activo"
        DEVUELTO = "devuelto", "Devuelto"
        VENCIDO = "vencido", "Vencido"

    usuario = models.ForeignKey(PerfilBiblioteca, on_delete=models.PROTECT, related_name="prestamos")
    libro = models.ForeignKey(Libro, on_delete=models.PROTECT, related_name="prestamos")
    fecha_prestamo = models.DateField(default=timezone.localdate)
    fecha_devolucion = models.DateField()
    devuelto_en = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["usuario", "devuelto_en"]),
                   models.Index(fields=["devuelto_en", "fecha_devolucion"])]

    @property
    def estado(self):
        if self.devuelto_en:
            return self.Estado.DEVUELTO
        return self.Estado.VENCIDO if self.dias_restantes < 0 else self.Estado.ACTIVO

    @property
    def dias_restantes(self):
        return (self.fecha_devolucion - (self.devuelto_en or timezone.localdate())).days

    @property
    def multa(self):
        return max(-self.dias_restantes, 0) * 2

