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
  Con `APP_ENV=staging` o `production` la app **no arranca** si `DATABASE_URL` es un superusuario, tiene
  `BYPASSRLS`, es miembro del migrador o no es miembro de `vectoredit_platform` (`check_app_role()` en
  `app/core/db.py`). Alembic sí corre con el migrador: en esos entornos la app y las migraciones usan
  `DATABASE_URL` distintos.
- Las pruebas de `tests/test_database_security.py` cambian de rol con `SET ROLE`, así que necesitan que
  `DATABASE_URL` sea un superusuario (o miembro de los tres roles).
- La migración `0010` la corre un usuario que pueda crear roles (tu superusuario). Después, las migraciones
  se pueden correr con `vectoredit_migrator_login`.
- Los roles son de todo el servidor PostgreSQL, no de una base: si tienes varias bases locales, las comparten.

Para probar como el agente desde la terminal:

```bash
psql -d test_1 -U vectoredit_agent_login -c "DELETE FROM platform.accounts"   # permission denied
```

## Worker de mantenimiento

Después de aplicar las migraciones, crea su login como administrador de PostgreSQL. Pasa la
contraseña local al script sin guardarla en el repositorio.

```bash
psql -d test_1 -v ON_ERROR_STOP=1 -v worker_password='<contraseña>' \
  -f scripts/create_worker_role.sql
```

Ejecuta `python -m app.jobs.worker` en un proceso separado de la API con `DATABASE_URL` para
`vectoredit_worker_login`. El proceso requiere un login de worker. La retención de la cola y la caducidad de
exportaciones están integradas. Las demás limpiezas se activan al conectar su servicio.

### Encolar y ejecutar

El módulo que origina un trabajo llama a `app.jobs.service.enqueue_job(db, request)` con un
`app.jobs.schemas.JobRequest`, dentro de la transacción que lo origina. La función devuelve el ID
del trabajo. Repetir el mismo tipo y payload con la misma clave del espacio devuelve ese mismo ID
y conserva la fecha de ejecución original. Las claves que empiezan con `scheduled:` están
reservadas al worker. El worker retira en lotes de hasta 1.000 filas los trabajos programados
que llevan más de 30 días en estado terminal. Los trabajos a demanda, como las exportaciones,
conservan su historial. Borrar un espacio borra sus trabajos dependientes.

El worker reclama lotes de hasta 10 trabajos con `FOR UPDATE SKIP LOCKED`. El lease de cinco minutos
permite recuperar los reclamos abandonados. Cada reclamo tiene un número de intento y un reclamo
anterior queda inválido cuando otro worker toma el trabajo. Durante la ejecución se mantiene
bloqueada la fila para impedir que otro worker la tome aunque venza el lease.

Los efectos en PostgreSQL y el estado final se confirman juntos. Si el handler falla, se revierten
sus cambios y el trabajo se reprograma con espera exponencial, comenzando en 30 segundos.
Tras cinco intentos queda en `failed`. El registro incluye el ID, tipo, intento y clase de error.
El código de error se guarda sin exponer mensajes ni payloads.

### Conectar un handler

El worker reconoce estas funciones exportadas desde el `service` del módulo dueño de los datos.

| Firma | Módulo | Frecuencia |
|---|---|---|
| `expire_uploads_and_reservations(db, as_of)` | `storage` | Cada 5 minutos |
| `purge_trash(db, older_than)` | `documents` | Diaria, con antigüedad de 30 días |
| `prune_versions(db)` | `documents` | Diaria, según el límite del plan |
| `delete_unused_objects(db, older_than)` | `storage` | Diaria, con antigüedad de 8 días |
| `reconcile_storage_quotas(db)` | `storage` | Diaria |
| `expire_exports(db, job)` | `jobs` | Cada hora, por espacio |
| `generate_export(db, job)` | `jobs` | A demanda |

El worker valida al arrancar que cada función instalada acepte la llamada. Entrega `as_of` y
`older_than` como objetos `datetime` con zona horaria. Para exportaciones, `job` es un
`JobContext` con el ID del trabajo, su espacio y el payload. Los servicios de VEC-31 y VEC-43
implementan las limpiezas. La migración `0017` incluye la tabla de exportaciones. El servicio
que genere el archivo se conecta mediante `generate_export` cuando esté implementado. El worker
omite la generación si la solicitud venció. La caducidad marca la exportación como `expired`
y suelta la referencia al archivo. El módulo de almacenamiento puede retirarlo después si comprueba
que ya no está en uso.

El handler deja el commit y el rollback al worker. La sesión del handler está dentro de un
savepoint para que un commit local conserve la atomicidad con el estado del trabajo. Si modifica
un servicio externo, usa el ID del trabajo como referencia estable para que una repetición sea
segura. El handler de almacenamiento comprueba las referencias bajo bloqueo antes de borrar un archivo.

## Variables de entorno

Todas se leen en `app/core/config.py`. `.env` nunca se sube al repo; `.env.example` sí, sin claves reales.

| Variable | Para qué | Ejemplo |
|---|---|---|
| `APP_ENV` | `development`, `staging` o `production`. En producción se ocultan Swagger y ReDoc. | `development` |
| `DATABASE_URL` | Conexión a PostgreSQL. Usa el driver `psycopg`. En la nube, agrega `?sslmode=require`. | `postgresql+psycopg://user@localhost:5432/test_1` |
| `FRONTEND_URL` | Dónde corre el editor. Solo él (y Swagger) puede mandar peticiones que cambian datos; los enlaces de correo apuntan aquí. | `http://localhost:5173` |
| `API_URL` | Dónde corre esta API. Google vuelve a `<API_URL>/api/v1/auth/google/callback`. | `http://localhost:8000` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Inicio de sesión con Google. Opcionales en desarrollo (sin ellas, Google responde 503). | — |
| `SESSION_COOKIE_DOMAIN` | Dominio de la cookie de sesión. Vacío en local; el dominio padre si el agente está en otro subdominio. | `vectoredit.com` |

Si falta una variable obligatoria, la app no arranca y dice cuál falta. Fuera de desarrollo, además, son
obligatorias las de Google y `FRONTEND_URL` y `API_URL` deben usar `https`.
Las variables del almacenamiento S3 se agregan con `storage/` (VEC-42).

## Iniciar sesión en local

**Con enlace por correo.** Todavía no hay proveedor de correo (VEC-40): en desarrollo el enlace se escribe
en la consola de `uvicorn`, con el correo enmascarado:

```
Sign-in link for a***@example.com (development only): http://localhost:5173/sign-in/email#token=...
```

Ábrelo con el editor corriendo, o copia el `token` y mándalo a `POST /api/v1/auth/sessions` desde Swagger.
Fuera de desarrollo, pedir un enlace responde 503 hasta que se elija el proveedor.

**Con Google.** Crea un cliente OAuth en Google Cloud Console (Credentials → OAuth client ID → Web
application) con la URI de redirección `http://localhost:8000/api/v1/auth/google/callback`, y pon
`GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` en tu `.env`. Luego abre `http://localhost:8000/api/v1/auth/google`
en el navegador.

**Desde Swagger.** Abre `/docs` en `http://localhost:8000`, no en `127.0.0.1:8000`: las peticiones que
cambian datos solo se aceptan desde `FRONTEND_URL` o `API_URL` (protección CSRF), y el navegador manda el
origen tal como está escrito en la barra.

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
| `requirements.txt` | Lo que corre en producción. Incluye `httpx2`, que usan Authlib para hablar con Google y el `TestClient` de las pruebas. |
| `requirements-dev.txt` | Lo anterior + pytest, ruff y mypy. |
| `pyproject.toml` | Configuración de ruff, mypy y pytest. |
