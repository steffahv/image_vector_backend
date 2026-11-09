# Image Vector Backend

Backend de plataforma de VectorEdit: cuentas, documentos, archivos y cobro.
Python 3.11 con FastAPI, SQLAlchemy 2, Alembic y Pydantic, sobre PostgreSQL y almacenamiento tipo S3.

El agente de diseño es otro servicio, en TypeScript, y no forma parte de este repo.
Los dos comparten la misma base PostgreSQL, cada uno con su propio rol.

## Arranque rápido

Necesitas Python 3.11+ y PostgreSQL instalado. Cada persona usa **su propia base local**;
lo que se comparte es el repo con sus migraciones.

### 1. Crear tu base de datos (solo la primera vez)

Alembic crea las tablas, pero **no crea la base**. Créala una vez con el nombre `test_1`.

**Mac**

```bash
brew install postgresql@17          # si no lo tienes
brew services start postgresql@17
createdb test_1
```

Tu `DATABASE_URL`: `postgresql+psycopg://<tu_usuario_de_mac>@localhost:5432/test_1`

**Windows**

1. Instala PostgreSQL desde https://www.postgresql.org/download/windows/
   (marca **PostgreSQL Server**, **pgAdmin 4** y **Command Line Tools**; anota la contraseña de `postgres`).
2. Crea la base, con una de estas dos formas:
   - **pgAdmin:** Servers → PostgreSQL → clic derecho en **Databases** → **Create → Database…** → nombre `test_1` → **Save**.
   - **PowerShell** (cambia `17` por tu versión):
     ```powershell
     & "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres test_1
     ```

Tu `DATABASE_URL`: `postgresql+psycopg://postgres:<tu_contraseña>@localhost:5432/test_1`

**Linux (Debian/Ubuntu)**

```bash
sudo apt install postgresql
sudo -u postgres createuser --superuser $USER
createdb test_1
```

Tu `DATABASE_URL`: `postgresql+psycopg://<tu_usuario>@localhost:5432/test_1`

### 2. Configurar y arrancar

```bash
cp .env.example .env            # pon tu DATABASE_URL del paso 1
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head            # crea las tablas en tu base
uvicorn app.main:app --reload
```

Más detalle (contraseñas con caracteres especiales, cómo comprobar la base, reiniciarla):
[docs/desarrollo.md](docs/desarrollo.md).

### 3. Abrir

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
