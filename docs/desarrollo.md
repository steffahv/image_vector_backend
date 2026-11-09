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

1. Descarga el instalador desde https://www.postgresql.org/download/windows/ y ejecútalo.
   - Deja marcados **PostgreSQL Server**, **pgAdmin 4** y **Command Line Tools**.
   - Pon una contraseña para el usuario `postgres` y **anótala**: la vas a usar en `DATABASE_URL`.
   - Deja el puerto en `5432`.
2. Crea la base `test_1`. Elige una de estas dos formas:

   **Con pgAdmin (visual)**
   1. Abre pgAdmin 4.
   2. En el panel izquierdo, abre **Servers → PostgreSQL** y escribe la contraseña de `postgres`.
   3. Clic derecho en **Databases → Create → Database…**
   4. En **Database** escribe `test_1` y pulsa **Save**.

   **Con la terminal (PowerShell)**

   El instalador no agrega los comandos de PostgreSQL al PATH, así que se usa la ruta completa
   (cambia `17` por tu versión):

   ```powershell
   & "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres test_1
   ```

   Te pedirá la contraseña de `postgres`.
3. Tu `DATABASE_URL` queda así:

```
DATABASE_URL=postgresql+psycopg://postgres:<tu_contraseña>@localhost:5432/test_1
```

Si la contraseña tiene caracteres especiales (`@`, `:`, `/`, `#`), cámbialos por su código:
`@` → `%40`, `:` → `%3A`, `/` → `%2F`, `#` → `%23`.

**Comprobar que la base existe** (cualquier sistema):

```bash
psql -d test_1 -c "select 1"                     # Mac / Linux
```

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d test_1 -c "select 1"   # Windows
```

Si responde `1`, la base está lista.

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

## Roles en tu base local

La migración `0010` crea los roles `vectoredit_migrator`, `vectoredit_platform` y `vectoredit_agent`
(qué puede cada uno: [base-de-datos.md](base-de-datos.md#roles-y-seguridad-por-fila)). Así que con
`alembic upgrade head` ya los tienes. Son roles **sin login**; si quieres entrar con ellos, crea un usuario
con contraseña por cada uno (elige tus contraseñas, no se guardan en ningún lado del repo):

```bash
psql -d test_1 -v ON_ERROR_STOP=1 \
  -v migrator_password=<contraseña> -v platform_password=<contraseña> -v agent_password=<contraseña> \
  -f scripts/create_login_roles.sql                                                 # Mac / Linux
```

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d test_1 -v ON_ERROR_STOP=1 `
  -v migrator_password=<contraseña> -v platform_password=<contraseña> -v agent_password=<contraseña> `
  -f scripts/create_login_roles.sql                                                 # Windows
```

Crea `vectoredit_migrator_login`, `vectoredit_platform_login` y `vectoredit_agent_login`. Si lo corres otra vez,
solo cambia las contraseñas.

Para el día a día puedes seguir con tu superusuario en `DATABASE_URL`, pero ten en cuenta:

- **Un superusuario se salta la seguridad por fila.** La app funciona, pero no te protege. Para ver lo mismo
  que verá la app desplegada, usa `vectoredit_platform_login` en `DATABASE_URL` (las migraciones siguen
  necesitando el migrador o tu superusuario).
- Las pruebas de `tests/test_database_security.py` cambian de rol con `SET ROLE`, así que necesitan que
  `DATABASE_URL` sea un superusuario (o miembro de los tres roles).
- La migración `0010` la corre un usuario que pueda crear roles (tu superusuario). Después, las migraciones
  se pueden correr con `vectoredit_migrator_login`.
- Los roles son de todo el servidor PostgreSQL, no de una base: si tienes varias bases locales, las comparten.

Para probar como el agente desde la terminal:

```bash
psql -d test_1 -U vectoredit_agent_login -c "DELETE FROM platform.accounts"   # permission denied
```

## Variables de entorno

Todas se leen en `app/core/config.py`. `.env` nunca se sube al repo; `.env.example` sí, sin claves reales.

| Variable | Para qué | Ejemplo |
|---|---|---|
| `APP_ENV` | `development`, `staging` o `production`. En producción se ocultan Swagger y ReDoc. | `development` |
| `DATABASE_URL` | Conexión a PostgreSQL. Usa el driver `psycopg`. En la nube, agrega `?sslmode=require`. | `postgresql+psycopg://user@localhost:5432/test_1` |

Si falta una variable obligatoria, la app no arranca y dice cuál falta.
Las variables del almacenamiento S3 se agregan con `storage/` (VEC-42).

## Trabajar en equipo con la base

- **Cada uno tiene su base local.** Nadie trabaja sobre la base de otro.
- **Las tablas viven en las migraciones** (`alembic/versions/`), dentro del repo.
- Cuando cambias una tabla: generas la migración, la aplicas en tu base, la pruebas y la subes en tu PR.
- Cuando alguien sube una migración: `git pull` y `alembic upgrade head`. Tu base queda igual a la suya.
- Si tu base queda en mal estado: `dropdb test_1 && createdb test_1 && alembic upgrade head`.
- Si dos ramas crean migraciones a la vez, Alembic avisa que hay dos «heads». Se resuelve en la segunda rama
  con `alembic merge heads -m "merge"` o cambiando su `down_revision` a la última de `main`.

### Entornos desplegados (más adelante)

Desarrollo, staging y producción tendrán bases separadas. Cómo se crean y cómo se migran se define en VEC-37.

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
- Cada tabla nueva se importa en el `models/__init__.py` de su módulo, y cada módulo nuevo con `models/` se registra
  en `app/core/models_registry.py`. Si falta alguno de los dos, Alembic no ve la tabla.
- Los nombres de índices y restricciones salen de `NAMING_CONVENTION` en `app/core/model_base.py`.

## Swagger

FastAPI genera la documentación de la API a partir del código.

| URL | Qué es |
|---|---|
| `/docs` | Swagger UI: ver y probar cada ruta. |
| `/redoc` | ReDoc: la misma documentación, para leer. |
| `/api/v1/openapi.json` | El esquema OpenAPI. De aquí se generarán los tipos TypeScript para el editor y el agente. |

- Los grupos de Swagger son los tags de `app/core/openapi.py`. Cada módulo tiene el suyo.
- Para que una ruta quede bien documentada: `response_model`, un `summary` corto y `schemas/` con tipos precisos.
- Con `APP_ENV=production` las tres URLs responden 404.

## Pruebas y CI

```bash
ruff check . && ruff format --check .   # lint y formato
mypy                                    # tipos (modo estricto)
pytest                                  # pruebas
```

Las pruebas leen `DATABASE_URL` de tu `.env` y algunas usan la base, así que antes necesitas el `.env` y `alembic upgrade head`.
No dejan datos: cada una se deshace al terminar.

`.github/workflows/ci.yml` corre en cada PR y en cada push a `main`:

1. Instala `requirements-dev.txt`.
2. Lint y formato con ruff.
3. Tipos con mypy.
4. `alembic upgrade head`, `downgrade base` y otra vez `upgrade head` contra un PostgreSQL real.
5. Crea los usuarios con login con `scripts/create_login_roles.sql` (contraseñas de usar y tirar, solo para la CI).
6. `alembic check` conectado como `vectoredit_migrator_login`, que no es superusuario (detecta modelos sin migración
   y que el migrador puede trabajar solo).
7. pytest. `AGENT_DATABASE_URL` activa la prueba que entra con el usuario real del agente.

## Dependencias

| Archivo | Qué lleva |
|---|---|
| `requirements.txt` | Lo que corre en producción. |
| `requirements-dev.txt` | Lo anterior + pytest, httpx, ruff y mypy. |
| `pyproject.toml` | Configuración de ruff, mypy y pytest. |
