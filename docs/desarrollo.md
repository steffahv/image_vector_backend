# Desarrollo

## Requisitos

- Python 3.11 o superior.
- PostgreSQL 16 o superior, instalado en tu máquina.

No se usa Docker. Cada persona tiene **su propia base local**; lo que se comparte es el repo con sus migraciones.

## Instalar PostgreSQL (una sola vez)

**Mac (Homebrew)**

```bash
brew install postgresql@17
brew services start postgresql@17
createdb test_1
```

Tu `DATABASE_URL` queda así (sin contraseña, con tu usuario de la Mac):

```
DATABASE_URL=postgresql+psycopg://<tu_usuario>@localhost:5432/test_1
```

**Windows**

1. Descarga el instalador desde https://www.postgresql.org/download/windows/ e instálalo.
   Anota la contraseña que pongas para el usuario `postgres`.
2. Abre pgAdmin (viene con el instalador) y crea una base llamada `test_1`,
   o en una terminal: `createdb -U postgres test_1`.
3. Tu `DATABASE_URL` queda así:

```
DATABASE_URL=postgresql+psycopg://postgres:<tu_contraseña>@localhost:5432/test_1
```

**Linux (Debian/Ubuntu)**

```bash
sudo apt install postgresql
sudo -u postgres createuser --superuser $USER
createdb test_1
```

> Alembic crea y cambia las **tablas**, pero no crea la **base**. Por eso `createdb` va una sola vez antes.

## Primer arranque

```bash
cp .env.example .env            # pon tu DATABASE_URL
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Día a día:

```bash
source .venv/bin/activate
alembic upgrade head            # por si alguien subió migraciones nuevas
uvicorn app.main:app --reload
```

## Variables de entorno

Todas se leen en `app/core/config.py`. `.env` nunca se sube al repo; `.env.example` sí, sin claves reales.

| Variable | Para qué | Ejemplo |
|---|---|---|
| `APP_ENV` | `development`, `staging` o `production`. En producción se ocultan Swagger y ReDoc. | `development` |
| `DATABASE_URL` | Conexión a PostgreSQL. Usa el driver `psycopg`. En la nube, agrega `?sslmode=require`. | `postgresql+psycopg://user@localhost:5432/test_1` |

Si falta una variable obligatoria, la app no arranca y dice cuál falta.
Las variables del almacenamiento (S3/R2) se agregan con `storage/` (VEC-42).

## Trabajar en equipo con la base

- **Cada uno tiene su base local.** Nadie trabaja sobre la base de otro.
- **Las tablas viven en las migraciones** (`alembic/versions/`), dentro del repo.
- Cuando cambias una tabla: generas la migración, la aplicas en tu base, la pruebas y la subes en tu PR.
- Cuando alguien sube una migración: `git pull` y `alembic upgrade head`. Tu base queda igual a la suya.
- Si tu base queda en mal estado: `dropdb test_1 && createdb test_1 && alembic upgrade head`.
- Si dos ramas crean migraciones a la vez, Alembic avisa que hay dos «heads». Se resuelve en la segunda rama
  con `alembic merge heads -m "merge"` o cambiando su `down_revision` a la última de `main`.

### Base compartida (staging, más adelante)

Habrá una sola base en la nube para staging (VEC-37). Solo la toca `main`: al unirse un PR, la CI corre
`alembic upgrade head` contra ella. Sirve para que el editor y el agente prueben contra un backend real.
Nadie desarrolla directamente sobre ella.

## Migraciones (Alembic)

Alembic es la herramienta que crea y cambia las tablas. Es el único que modifica el esquema.

```bash
alembic revision --autogenerate -m "add documents table"   # genera la migración
alembic upgrade head                                        # la aplica
alembic downgrade -1                                        # deshace la última
alembic current                                             # versión aplicada
```

- Revisa siempre el archivo generado en `alembic/versions/` antes de aplicarlo: autogenerate no detecta todo
  (por ejemplo, cambios de nombre de columna o políticas de seguridad por fila).
- Si creas un módulo nuevo con `models.py`, regístralo en `app/core/models_registry.py` o Alembic no verá sus tablas.
- Los nombres de índices y restricciones salen de `NAMING_CONVENTION` en `app/core/db.py`.

## Swagger

FastAPI genera la documentación de la API a partir del código.

| URL | Qué es |
|---|---|
| `/docs` | Swagger UI: ver y probar cada ruta. |
| `/redoc` | ReDoc: la misma documentación, para leer. |
| `/api/v1/openapi.json` | El esquema OpenAPI. De aquí se generarán los tipos TypeScript para el editor y el agente. |

- Los grupos de Swagger son los tags de `app/core/openapi.py`. Cada módulo tiene el suyo.
- Para que una ruta quede bien documentada: `response_model`, un `summary` corto y `schemas.py` con tipos precisos.
- Con `APP_ENV=production` las tres URLs responden 404.

## Pruebas y CI

```bash
ruff check . && ruff format --check .   # lint y formato
mypy                                    # tipos (modo estricto)
pytest                                  # pruebas
```

Las pruebas leen `DATABASE_URL` de tu `.env`, así que necesitas haberlo creado antes.

`.github/workflows/ci.yml` corre en cada PR y en cada push a `main`:

1. Instala `requirements-dev.txt`.
2. Lint y formato con ruff.
3. Tipos con mypy.
4. `alembic upgrade head` y `alembic check` contra un PostgreSQL real (detecta modelos sin migración).
5. pytest.

## Dependencias

| Archivo | Qué lleva |
|---|---|
| `requirements.txt` | Lo que corre en producción. |
| `requirements-dev.txt` | Lo anterior + pytest, httpx, ruff y mypy. |
| `pyproject.toml` | Configuración de ruff, mypy y pytest. |
