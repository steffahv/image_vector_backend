# Base de datos

Cómo se escriben las tablas en este repo. Las tablas, columnas y relaciones salen de
`Modelo_relacional_VectorEdit` (adjunto en Jira, Epic VEC-28); aquí se explica cómo pasarlas a código.

## Esquemas

Toda tabla vive en uno de estos esquemas, nunca en `public`. Los crea la migración `0002`.

| Esquema | En el modelo relacional | Dónde van sus modelos | Tarea |
|---|---|---|---|
| `auth` | `auth` | `app/auth/models/` | VEC-29 |
| `platform` | `plataforma` | `app/documents/models/` | VEC-29 |
| `storage` | `almacenamiento` | `app/storage/models/` | VEC-29 |
| `billing` | `cobro` | `app/billing/models/` | VEC-41 |
| `agent` | `agente` | `app/agent/models/` | VEC-41 |
| `operations` | `operacion` | `app/jobs/models/` | VEC-41 |

En el código se usan con `DbSchema` (`app/core/model_base.py`): `DbSchema.PLATFORM`, `DbSchema.BILLING`, etc.

## Nombres en inglés

El modelo relacional está en español; **en la base todo va en inglés**: esquemas, tablas, columnas y valores de estado.

- Tablas en plural y `snake_case`: `cuentas` → `accounts`, `movimientos_credito` → `credit_movements`.
- Columnas en singular y `snake_case`. Las fechas terminan en `_at` y las referencias en `_id`.
- Valores de estado en inglés: `borrador, activo, papelera` → `draft, active, trash`.

Columnas que se repiten en muchas tablas:

| Modelo relacional | En la base |
|---|---|
| `creado_at` | `created_at` |
| `modificado_at` | `updated_at` |
| `eliminado_at` | `deleted_at` |
| `espacio_id` | `workspace_id` |
| `cuenta_id` | `account_id` |
| `documento_id` | `document_id` |
| `propietario_id` | `owner_id` |
| `usuario_auth_id` | `auth_user_id` |
| `nombre` | `name` |
| `estado` | `status` |
| `origen` | `source` |

### Tablas de VEC-29 (las que otras tablas referencian)

Si una tabla tuya apunta a una de estas, usa estos nombres. **Todas existen:**

- Migración `0003`: `auth.users`, `auth.accounts`, `auth.sessions`, `auth.verifications` y `platform.accounts`.
- Migración `0005`: `platform.workspaces`, `platform.folders`, `platform.documents`, `platform.document_revisions`,
  `platform.document_versions` y `storage.objects`.
- Migración `0006`: `platform.revision_images`, `platform.share_links`, `storage.saves`, `storage.uploads`,
  `storage.workspace_quotas` y `storage.byte_reservations`.

Con eso están las 17 tablas de VEC-29.

| Modelo relacional | En la base | Clave que se referencia |
|---|---|---|
| `auth.user` | `auth.users` | `id` |
| `auth.account` | `auth.accounts` | — |
| `auth.session` | `auth.sessions` | — |
| `auth.verification` | `auth.verifications` | — |
| `plataforma.cuentas` | `platform.accounts` | `id` |
| `plataforma.espacios` | `platform.workspaces` | `id` |
| `plataforma.carpetas` | `platform.folders` | `(workspace_id, id)` |
| `plataforma.documentos` | `platform.documents` | `(workspace_id, id)` |
| `plataforma.revisiones_documento` | `platform.document_revisions` | `(workspace_id, document_id, revision)` |
| `plataforma.imagenes_revision` | `platform.revision_images` | — |
| `plataforma.versiones_documento` | `platform.document_versions` | `(workspace_id, document_id, id)` |
| `plataforma.enlaces_compartidos` | `platform.share_links` | — |
| `almacenamiento.objetos` | `storage.objects` | `(workspace_id, id)` |
| `almacenamiento.subidas` | `storage.uploads` | `(workspace_id, id)` |
| `almacenamiento.guardados` | `storage.saves` | `(workspace_id, id)` |
| `almacenamiento.cupos_espacio` | `storage.workspace_quotas` | — |
| `almacenamiento.reservas_bytes` | `storage.byte_reservations` | — |

Columnas de VEC-29 con traducción no evidente:

| Tabla | Modelo relacional | En la base |
|---|---|---|
| `documents` | `revision_actual` | `current_revision` |
| `document_revisions` | `objeto_json_id`, `objeto_miniatura_id` | `json_object_id`, `thumbnail_object_id` |
| `document_revisions` | `bytes_json_original`, `autor_tipo` | `original_json_bytes`, `author_type` (`account`, `agent`) |
| `document_versions` | `etiqueta`, `protegida_hasta` | `label`, `protected_until` |
| `objects` | `clase`, `bytes`, `codificacion` | `kind`, `size_bytes`, `encoding` |
| `objects` | `sin_referencias_desde`, `copia_verificada_at` | `unreferenced_since`, `copy_verified_at` |
| `revision_images` | `hash_editor`, `objeto_imagen_id` | `editor_hash`, `image_object_id` |
| `share_links` | `activo`, `permite_descarga`, `expira_at` | `active`, `allows_download`, `expires_at` |
| `saves` | `clave_idempotencia`, `huella_solicitud` | `idempotency_key`, `request_fingerprint` |
| `saves` | `revision_base`, `revision_resultado` | `base_revision`, `result_revision` |
| `uploads` | `clave_temporal`, `bytes_maximos`, `sha256_declarado` | `temp_key`, `max_bytes`, `declared_sha256` |
| `uploads` | `lease_hasta`, `error_codigo` | `lease_until`, `error_code` |
| `workspace_quotas` | `limite_bytes`, `usados_bytes`, `reservados_bytes` | `limit_bytes`, `used_bytes`, `reserved_bytes` |
| `byte_reservations` | `cantidad` | `amount` |

Las tablas de `billing`, `agent` y `operations` las traduce VEC-41 con las mismas reglas y las agrega a esta lista.

## Molde de una tabla

Toda tabla hereda de `Base` y, salvo que el modelo diga otra cosa, de `UUIDPrimaryKey` y `Timestamps`:

| Viene de | Columna | Tipo en PostgreSQL |
|---|---|---|
| `UUIDPrimaryKey` | `id` | `uuid` v7, generado por la base (`uuidv7()`): empieza con la fecha de creación, así los índices crecen en orden |
| `Timestamps` | `created_at`, `updated_at` | `timestamptz`, con `now()` por defecto |
| `CreatedAt` | `created_at` | Igual, para filas que no cambian después de insertarse (revisiones, versiones, objetos) |

Los tipos se ponen solos según la anotación de Python:

| Anotación | Tipo en PostgreSQL |
|---|---|
| `Mapped[str]` | `text` |
| `Mapped[bytes]` | `bytea` (por ejemplo, hashes) |
| `Mapped[uuid.UUID]` | `uuid` |
| `Mapped[datetime]` | `timestamptz` |
| `Mapped[int]` | `integer`; para tamaños y revisiones usa `mapped_column(BigInteger)` |
| `Mapped[X \| None]` | la columna acepta nulos (en el modelo: «nulo») |

Sin `\| None`, la columna es `NOT NULL`.

## Ejemplo

`platform.folders`: carpeta dentro de un espacio, con carpeta padre opcional del **mismo** espacio.
Versión resumida de `app/documents/models/folder.py` (el archivo real además impide que una carpeta sea su propio padre).

```python
import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class Folder(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "folders"
    __table_args__ = (
        # Permite que otras tablas apunten a (workspace_id, id).
        UniqueConstraint("workspace_id", "id"),
        # La carpeta padre tiene que estar en el mismo espacio.
        ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["platform.folders.workspace_id", "platform.folders.id"],
        ),
        {"schema": DbSchema.PLATFORM},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.workspaces.id"))
    parent_id: Mapped[uuid.UUID | None]
    name: Mapped[str]
```

SQL que genera:

```sql
CREATE TABLE platform.folders (
    workspace_id UUID NOT NULL,
    parent_id UUID,
    name TEXT NOT NULL,
    id UUID DEFAULT uuidv7() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_folders PRIMARY KEY (id),
    CONSTRAINT uq_folders_workspace_id_id UNIQUE (workspace_id, id),
    CONSTRAINT fk_folders_workspace_id_parent_id_folders
        FOREIGN KEY (workspace_id, parent_id) REFERENCES platform.folders (workspace_id, id),
    CONSTRAINT fk_folders_workspace_id_workspaces
        FOREIGN KEY (workspace_id) REFERENCES platform.workspaces (id)
);
```

## Reglas

- **Referencias dentro de un espacio:** el modelo pide FK compuestas (§IX) para que documento, revisión,
  carpeta y objeto sean del mismo espacio. La tabla referenciada declara `UniqueConstraint("workspace_id", "id")`
  y la que apunta usa `ForeignKeyConstraint` con las dos columnas, como en el ejemplo.
- **Referencias simples** (a `accounts.id`, `workspaces.id`): `mapped_column(ForeignKey("platform.accounts.id"))`.
  Siempre con el esquema delante.
- **Estados** (§X): un `StrEnum` de Python guardado como texto con `CHECK`, no un enum nativo de PostgreSQL
  (cambiar un enum nativo en una migración es incómodo). Usa `text_enum()` de `app/core/model_base.py`,
  con el nombre de la columna:

  ```python
  class DocumentStatus(StrEnum):
      DRAFT = "draft"
      ACTIVE = "active"
      TRASH = "trash"


  class Document(UUIDPrimaryKey, Timestamps, Base):
      ...
      status: Mapped[DocumentStatus] = mapped_column(text_enum(DocumentStatus, "status"))
  ```

  Genera `CHECK (status IN ('draft', 'active', 'trash'))` con el nombre `ck_documents_status`.

- **Borrado:** sin `ondelete="CASCADE"` desde la cuenta (§IX-C). Solo los hijos que dependen por completo
  de su padre pueden borrarse en cascada, y se decide tabla por tabla.
- **Números no negativos** (tamaños, contadores): `CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative")`.
- Los nombres de PK, FK, UQ, índices y CHECK los pone `NAMING_CONVENTION`; no los escribas a mano.

## De modelo a migración

1. Escribe la tabla en su propio archivo dentro de `models/` del módulo (por ejemplo `app/documents/models/folder.py`)
   e impórtala en `models/__init__.py`. Si no se importa ahí, Alembic no la ve.
2. `alembic revision --autogenerate -m "add platform folders"`.
3. **Revisa el archivo generado** en `alembic/versions/`. Autogenerate no detecta todo: cambios de nombre,
   algunos CHECK, índices parciales ni políticas por fila. Si la tabla tiene datos de una cuenta, agrégale su
   política (ver [Política de una tabla nueva](#política-de-una-tabla-nueva)). Los permisos no hace falta tocarlos.
4. `alembic upgrade head`, luego `alembic downgrade -1` y otra vez `alembic upgrade head`: la migración tiene que ir y volver.
   Al generarla, Alembic la formatea con ruff (`alembic.ini`), así pasa el lint de la CI.
5. `alembic check` debe decir `No new upgrade operations detected`.

## Roles y seguridad por fila

La plataforma (este repo) y el agente (TypeScript) comparten la base. Cada uno entra con su propio
usuario y solo con los permisos que necesita, y PostgreSQL filtra las filas por la cuenta conectada.
Así la protección no depende solo de que cada consulta esté bien escrita. Lo crea la migración `0010`.

### Qué rol accede a qué esquema

| Esquema | `vectoredit_migrator` | `vectoredit_platform` | `vectoredit_agent` |
|---|---|---|---|
| `auth` | dueño | lee y escribe | lee solo `users` y `sessions` |
| `platform` | dueño | lee y escribe | lee |
| `storage` | dueño | lee y escribe | — |
| `billing` | dueño | lee y escribe | — |
| `operations` | dueño | lee y escribe | — |
| `agent` | dueño | lee | lee y escribe |

- **`vectoredit_migrator`** es el dueño de los esquemas y de todas las tablas, y el único que puede crear
  o cambiar tablas. Lo usa Alembic y ninguna aplicación en marcha: `alembic/env.py` hace `SET ROLE` a él antes
  de migrar, así toda tabla nueva tiene el mismo dueño.
- **`vectoredit_platform`** es la app de este repo.
- **`vectoredit_agent`** es el agente. Créditos y cupos los cambia solo con funciones SQL autorizadas (VEC-41).
  En `auth` solo lee `users` y `sessions`, lo justo para validar la sesión: nunca ve contraseñas ni enlaces
  de correo. Si el agente necesita otra tabla de `auth`, se le da en una migración nueva, tabla por tabla.

Los tres son roles de grupo **sin login**. En cada entorno se crea un usuario con contraseña por servicio
(`vectoredit_<rol>_login`), miembro de su rol, con `scripts/create_login_roles.sql`. Las contraseñas nunca van
al repo y cada servicio tiene las suyas. Cómo crearlos en tu base local: [desarrollo.md](desarrollo.md#roles-en-tu-base-local).

Salvo esa excepción en `auth`, los permisos se dan **por esquema**, no tabla por tabla, y con `ALTER DEFAULT PRIVILEGES`: una tabla que el
migrador cree después recibe sola los permisos de la tabla de arriba. Para cambiar quién accede a un esquema,
se hace en una migración nueva, no a mano.

### La cuenta conectada

Cada transacción empieza fijando la cuenta con `SET LOCAL` (en Python, `set_config('app.account_id', ..., true)`).
`platform.current_account_id()` la devuelve, o `NULL` si no hay ninguna. Como `SET LOCAL` termina con la
transacción, la cuenta no pasa a la siguiente petición aunque SQLAlchemy reutilice la conexión.

En el código:

```python
from app.core.db import get_db, set_current_account


def handler(db: Session = Depends(get_db)) -> ...:
    set_current_account(db, account.id)  # desde aquí, toda consulta queda filtrada por esa cuenta
```

`set_current_account()` vale para toda la sesión: se vuelve a aplicar al empezar cada transacción, también
después de un `commit()`. También se vuelve a aplicar después de deshacer un savepoint (`begin_nested()`),
porque PostgreSQL deshace con él el `SET LOCAL` hecho adentro. Lo llamará la dependencia de autenticación (VEC-4).
El agente hace lo mismo con su conexión: `SELECT set_config('app.account_id', $1, true)` al abrir cada transacción.

**Sin cuenta fijada, las tablas con RLS no muestran filas ni aceptan escrituras.** Si una consulta devuelve
vacío sin motivo, revisa que se haya llamado a `set_current_account()`.

### El usuario conectado (inicio de sesión)

Al iniciar sesión se sabe qué usuario de `auth` entró, pero todavía no el id de su cuenta. Para eso está
`set_current_user()`, que fija `app.user_id` igual que la cuenta. La política de `platform.accounts` acepta la
cuenta fijada **o** la cuenta cuyo `auth_user_id` es el usuario conectado, así el inicio de sesión puede
encontrarla, o crearla la primera vez:

```python
set_current_user(db, auth_user.id)
account = db.scalar(select(Account).where(Account.auth_user_id == auth_user.id))
if account is None:
    account = Account(auth_user_id=auth_user.id, ...)  # primera vez
set_current_account(db, account.id)  # también limpia el usuario conectado
```

Solo `platform.accounts` usa el usuario conectado; las demás tablas filtran por la cuenta. En cuanto se fija la
cuenta, `set_current_account()` limpia el usuario conectado, así la sesión no sigue viendo más de una cuenta.

El `id` y el `auth_user_id` de una cuenta no se pueden cambiar (trigger `accounts_keep_identity`): una cuenta
no puede pasar a ser de otro usuario aunque el código tenga un error.

Las tablas de `auth` no tienen RLS: se consultan antes de saber qué cuenta es (iniciar sesión, validar la cookie).

### Política de una tabla nueva

Toda tabla con datos de una cuenta lleva su política, en la **misma migración** que la crea. Autogenerate no
la detecta: se agrega a mano debajo de `op.create_table(...)`. El modelo es `platform.accounts` (migración `0010`).

Si la tabla tiene `account_id`:

```python
def upgrade() -> None:
    op.create_table("...", ..., schema="billing")
    op.execute("ALTER TABLE billing.credit_movements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE billing.credit_movements FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY account_isolation ON billing.credit_movements
            USING (account_id = platform.current_account_id())
            WITH CHECK (account_id = platform.current_account_id())
        """
    )


def downgrade() -> None:
    op.drop_table("credit_movements", schema="billing")  # la política se borra con la tabla
```

Si la tabla tiene `workspace_id`, se compara con los espacios de la cuenta (ejemplo; ajústalo a cómo quede
`platform.workspaces` en VEC-29):

```sql
CREATE POLICY account_isolation ON platform.documents
    USING (workspace_id IN (
        SELECT id FROM platform.workspaces WHERE owner_id = platform.current_account_id()))
    WITH CHECK (workspace_id IN (
        SELECT id FROM platform.workspaces WHERE owner_id = platform.current_account_id()))
```

- `USING` filtra lo que se lee, actualiza y borra; `WITH CHECK` impide escribir filas de otra cuenta.
- `FORCE` hace que el dueño (el migrador) también quede filtrado. Solo los superusuarios se saltan RLS.
  Por eso **las pruebas de seguridad no corren como superusuario**: cambian al rol con `SET LOCAL ROLE`
  (ver `tests/test_database_security.py`). Agrega ahí la prueba de tu tabla.
- Una migración de datos que tenga que tocar filas de todas las cuentas corre como superusuario, o desactiva
  `FORCE` en esa migración y lo vuelve a activar al final.
- Tablas de cupos y créditos (`billing.credit_balances`, `billing.credit_reservations`, `agent.period_quotas`,
  `agent.reservations`): además de la política, el agente no debe escribirlas directo. La migración que
  las crea quita esos permisos (`REVOKE INSERT, UPDATE, DELETE ... FROM vectoredit_agent`) y da `EXECUTE`
  solo sobre las funciones de reserva y descuento (VEC-41).

### Funciones

Las funciones que crea el migrador **no las puede ejecutar nadie** hasta que la migración que las crea lo
permita (`ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, migración `0010`). Por eso
cada función nueva lleva su `GRANT EXECUTE` a los roles que la usan:

```sql
CREATE FUNCTION billing.reserve_credits(...) RETURNS ...
    LANGUAGE plpgsql
    SECURITY DEFINER                     -- corre como el migrador: se salta RLS a propósito
    SET search_path = pg_catalog, pg_temp
AS $$ ... $$;
GRANT EXECUTE ON FUNCTION billing.reserve_credits(...) TO vectoredit_agent;
```

- Una función `SECURITY DEFINER` se salta RLS, así que valida ella misma la cuenta
  (`platform.current_account_id()`) y nunca confía en un id que le pasen.
- Siempre con `SET search_path = pg_catalog, pg_temp` y nombres completos (`billing.credit_balances`), para
  que nadie pueda colarle una tabla o función con el mismo nombre.

## Pruebas contra la base

Las reglas de la base (CHECK, UQ, FK) se prueban contra PostgreSQL con el fixture `db` de `tests/conftest.py`:
cada prueba corre dentro de una transacción que se deshace al final, así que no deja datos.
Ejemplos: `tests/test_auth_tables.py`, `tests/test_document_tables.py` y `tests/test_storage_tables.py`.
Para crear filas de prueba (cuenta, espacio, archivo, documento, revisión) usa `tests/factories.py`
en lugar de repetirlas. Necesitan la base migrada (`alembic upgrade head`).

Si dos ramas crean migraciones a la vez, mira «Trabajar en equipo con la base» en [desarrollo.md](desarrollo.md).
