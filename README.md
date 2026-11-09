# Image Vector Backend

Backend de plataforma de VectorEdit: cuentas, documentos, archivos y cobro.
Python 3.11 con FastAPI, SQLAlchemy 2, Alembic y Pydantic, sobre PostgreSQL y almacenamiento tipo S3.

El agente de diseño es otro servicio, en TypeScript, y no forma parte de este repo.
Los dos comparten la misma base PostgreSQL, cada uno con su propio rol.

## Arranque rápido

Necesitas Python 3.11+ y PostgreSQL instalado. Cada persona usa su propia base local.

```bash
createdb test_1                 # crea tu base (solo la primera vez)
cp .env.example .env            # y pon tu DATABASE_URL
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head            # crea las tablas
uvicorn app.main:app --reload
```

- API: `http://127.0.0.1:8000/api/v1`
- Swagger: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Salud: `http://127.0.0.1:8000/api/v1/health`

## Documentación

| Documento | Qué explica |
|---|---|
| [docs/arquitectura.md](docs/arquitectura.md) | Para qué sirve cada módulo, qué archivo lleva cada uno, cómo se comunican y un ejemplo completo (guardar un documento). |
| [docs/desarrollo.md](docs/desarrollo.md) | Base local (Mac y Windows), variables de `.env`, migraciones en equipo, Swagger, pruebas y CI. |
| [docs/convenciones.md](docs/convenciones.md) | Reglas de código: idioma, nombres, tipos, comentarios y cómo agregar un módulo o una ruta. |

## Estructura

```text
app/
├── main.py              # Crea la app, configura Swagger y registra los routers
├── core/                # Configuración, base de datos, registro de modelos y metadatos de Swagger
├── health/              # GET /api/v1/health
├── auth/                # Cuentas y sesión
├── documents/           # Documentos, revisiones, versiones, carpetas, papelera y compartir
├── storage/             # Archivos en S3 y cuotas
├── billing/             # Planes, pagos y créditos
└── jobs/                # Trabajos de mantenimiento (proceso aparte, sin rutas)
alembic/                 # Migraciones de la base
tests/                   # Pruebas con pytest
docs/                    # Documentación del proyecto
```

## Antes de abrir un PR

```bash
ruff check . && ruff format --check .
mypy
pytest
```

La CI corre lo mismo y además aplica las migraciones contra un PostgreSQL real.
