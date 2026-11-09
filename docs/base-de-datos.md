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

Si una tabla tuya apunta a una de estas, usa estos nombres. **Ya existen:**

- Migración `0003`: `auth.users`, `auth.accounts`, `auth.sessions`, `auth.verifications` y `platform.accounts`.
- Migración `0005`: `platform.workspaces`, `platform.folders`, `platform.documents`, `platform.document_revisions`,
  `platform.document_versions` y `storage.objects`.

Las demás (`revision_images`, `share_links`, `uploads`, `saves`, `workspace_quotas` y `byte_reservations`)
llegan después en VEC-29.

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
   algunos CHECK, índices parciales ni políticas por fila.
4. `alembic upgrade head`, luego `alembic downgrade -1` y otra vez `alembic upgrade head`: la migración tiene que ir y volver.
   Al generarla, Alembic la formatea con ruff (`alembic.ini`), así pasa el lint de la CI.
5. `alembic check` debe decir `No new upgrade operations detected`.

## Pruebas contra la base

Las reglas de la base (CHECK, UQ, FK) se prueban contra PostgreSQL con el fixture `db` de `tests/conftest.py`:
cada prueba corre dentro de una transacción que se deshace al final, así que no deja datos.
Ejemplo: `tests/test_auth_tables.py`. Necesitan la base migrada (`alembic upgrade head`).

Si dos ramas crean migraciones a la vez, mira «Trabajar en equipo con la base» en [desarrollo.md](desarrollo.md).
