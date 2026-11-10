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
| `billing` | `cobro` | `app/billing/models/` | VEC-47 |
| `agent` | `agente` | `app/agent/models/` | VEC-41 |
| `operations` | `operacion` | `app/jobs/models/` | VEC-41 (`jobs` en VEC-36) |

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
- Migración `0011`: rotación del token de sesión (`auth.sessions.previous_token_hash` y `rotated_at`) y la
  función `auth.find_session(token_hash)`, con la que la plataforma y el agente validan la cookie
  ([arquitectura.md](arquitectura.md#inicio-de-sesión-y-sesiones-vec-4)).
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

### Tablas de VEC-41 (`agent` y `operations`)

Migración `0013`. Faltan `operations.jobs` (VEC-36) y `operations.exports`, que apunta a un trabajo y llega
cuando exista `jobs`. Las tablas de `billing` son de VEC-47.

| Modelo relacional | En la base | Clave que se referencia |
|---|---|---|
| `agente.conversaciones` | `agent.conversations` | `(account_id, workspace_id, id)` |
| `agente.mensajes` | `agent.messages` | — |
| `agente.ejecuciones` | `agent.runs` | `id` y `(account_id, id)` |
| `agente.llamadas_pendientes` | `agent.pending_calls` | — |
| `agente.cupos_periodo` | `agent.period_quotas` | `(account_id, period_id, resource)` |
| `agente.reservas` | `agent.reservations` | — |
| `agente.tarifas` | `agent.rates` | `id` |
| `agente.consumo` | `agent.usage` | — |
| `operacion.auditoria` | `operations.audit_log` | — |
| `operacion.copias_objetos` | `operations.object_copies` | — |
| `operacion.ejecuciones_respaldo` | `operations.backup_runs` | — |

Columnas con traducción no evidente:

| Tabla | Modelo relacional | En la base |
|---|---|---|
| `conversations` | `titulo` | `title` |
| `messages` | `secuencia`, `rol`, `contenido` | `sequence`, `role`, `content` |
| `runs` | `sesion_editor_id`, `revision_inicial` | `editor_session_id`, `initial_revision` |
| `runs` | `version_pre_agente_id`, `version_pre_agente_historica` | `pre_agent_version_id`, `recorded_pre_agent_version_id` |
| `runs` | `modo`, `variante`, `modelo` | `mode`, `variant`, `model` |
| `runs` | `version_prompt`, `huella_catalogo`, `lease_hasta`, `fin_at` | `prompt_version`, `catalog_fingerprint`, `lease_until`, `finished_at` |
| `pending_calls` | `herramienta`, `huella_argumentos`, `resultado` | `tool`, `arguments_fingerprint`, `result` |
| `period_quotas` | `periodo_id`, `recurso`, `inicio`, `fin` | `period_id`, `resource`, `starts_at`, `ends_at` |
| `period_quotas` | `asignado`, `reservado`, `consumido` | `allocated`, `reserved`, `consumed` |
| `reservations` | `ejecucion_id`, `cantidad` | `run_id`, `amount` |
| `rates` | `proveedor`, `precio_entrada_micro`, `precio_salida_micro` | `provider`, `input_price_micro`, `output_price_micro` |
| `rates` | `moneda`, `base_tokens`, `vigente_desde` | `currency`, `token_basis`, `effective_from` |
| `usage` | `tarifa_id`, `evento_id`, `tokens_entrada`, `tokens_salida` | `rate_id`, `event_id`, `input_tokens`, `output_tokens` |
| `usage` | `unidades`, `coste_estimado_micro`, `cobrado`, `duracion_ms` | `units`, `estimated_cost_micro`, `charged`, `duration_ms` |
| `audit_log` | `actor_opaco`, `accion`, `entidad_tipo`, `entidad_id` | `actor_ref`, `action`, `entity_type`, `entity_id` |
| `object_copies` | `destino`, `clave`, `bytes` | `destination`, `key`, `size_bytes` |
| `backup_runs` | `tipo`, `inicio_at`, `manifiesto` | `type`, `started_at`, `manifest` |
| `backup_runs` | `punto_recuperacion_at`, `resultado_verificacion` | `recovery_point_at`, `verification_result` |

Estados que el modelo dejaba abiertos (§X), fijados en esta migración:

| Columna | Valores |
|---|---|
| `runs.status` | `pending`, `running`, `completed`, `failed`, `cancelled`, `expired` (activos: los dos primeros) |
| `runs.mode` | `platform`, `own_key` (los mismos que `accounts.agent_mode`) |
| `reservations.status` | `reserved`, `settled` (liquidada), `released` |
| `pending_calls.status` | `pending`, `completed`, `failed`, `expired` |
| `messages.role` | `user`, `assistant`, `tool` |
| `usage.result` | `success`, `error`, `cancelled` |
| `audit_log.result` | `success`, `denied`, `error` |
| `backup_runs.type`, `status` | `database`, `objects`; `running`, `succeeded`, `failed` |

`period_quotas.resource`, `runs.variant` y `audit_log.action` quedan como texto: dependen de los planes y del
agente, y cambiarían con cada producto nuevo.

### Qué usa el agente (VEC-35)

| Tabla | El servicio del agente |
|---|---|
| `conversations`, `messages`, `runs`, `pending_calls` | lee y escribe |
| `usage` | lee e inserta; nunca cambia ni borra un consumo ya registrado |
| `period_quotas`, `reservations` | solo lee; reserva, liquida y libera con las [funciones de cupos](#funciones-de-cupos) |
| `rates` | solo lee |
| `platform.*` | lee (cuenta, espacio, documento y versiones) |
| `auth.users`, `auth.sessions` | lee, para validar la sesión con `auth.find_session()` |
| `billing` | solo llama las [funciones de créditos](#funciones-de-créditos) |
| `storage`, `operations` | sin acceso |

Al abrir cada transacción fija la cuenta con `SELECT set_config('app.account_id', $1, true)`
([La cuenta conectada](#la-cuenta-conectada)); sin eso no ve ni escribe ninguna fila.

### Tablas de VEC-47 (`billing`)

La migración `0015` crea las ocho tablas del modelo relacional §VI.

| Modelo relacional | En la base | Regla principal |
|---|---|---|
| `cobro.planes` | `billing.plans` | Código de plan como clave |
| `cobro.derechos_plan` | `billing.plan_entitlements` | Clave `(plan_id, version)` y límites versionados en JSONB |
| `cobro.suscripciones` | `billing.subscriptions` | Derechos fijados por `(plan_id, entitlement_version)` e ID único por pasarela |
| `cobro.eventos_pasarela` | `billing.gateway_events` | Evento único por pasarela y disponible antes de identificar la cuenta |
| `cobro.paquetes_credito` | `billing.credit_packs` | Créditos positivos y precio en centavos mayor o igual a cero |
| `cobro.saldos_credito` | `billing.credit_balances` | Una fila por cuenta con `0 <= reserved <= balance` |
| `cobro.movimientos_credito` | `billing.credit_movements` | Importe distinto de cero y clave `(account_id, reason, reference)` |
| `cobro.reservas_credito` | `billing.credit_reservations` | Una reserva por ejecución, con FK a `agent.runs(account_id, id)` |

Columnas con traducción no evidente.

| Tabla | Modelo relacional | En la base |
|---|---|---|
| `plan_entitlements` | `vigente_desde`, `limites` | `effective_from`, `limits` |
| `subscriptions` | `version_derechos`, `pasarela`, `pasarela_id` | `entitlement_version`, `gateway`, `gateway_subscription_id` |
| `subscriptions` | `periodo_inicio`, `periodo_fin`, `cancela_al_final`, `gracia_hasta` | `period_start`, `period_end`, `cancel_at_period_end`, `grace_until` |
| `gateway_events` | `evento_id`, `tipo`, `cuerpo`, `procesado_at` | `event_id`, `type`, `payload`, `processed_at` |
| `credit_packs` | `creditos`, `precio_centavos`, `moneda`, `pasarela_producto_id` | `credits`, `price_cents`, `currency`, `gateway_product_id` |
| `credit_balances` | `saldo`, `reservado` | `balance`, `reserved` |
| `credit_movements` | `cantidad`, `motivo`, `referencia` | `amount`, `reason`, `reference` |
| `credit_reservations` | `ejecucion_id`, `cantidad`, `expira_at` | `run_id`, `amount`, `expires_at` |

| Columna | Valores |
|---|---|
| `subscriptions.status` | `active`, `trialing`, `past_due`, `cancelled` |
| `gateway_events.status` | `pending`, `processed`, `failed` |
| `credit_reservations.status` | `reserved`, `settled`, `released` |

`limits.max_versions` es un entero positivo validado por Pydantic y PostgreSQL. Los derechos del plan
gratuito usan 10 y los de los planes de pago usan 50. Para cambiar los derechos se agrega una versión.
`billing.service.version_limit(db, account_id)` usa la versión fijada en una suscripción vigente, de
prueba o en gracia por impago. Si hay varias suscripciones válidas, usa el mayor límite. Devuelve
10 si no hay una suscripción visible y vigente. La sesión debe tener fijada la cuenta antes de llamarlo.

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
| `billing` | dueño | lee y escribe | solo funciones de créditos |
| `operations` | dueño | lee y escribe | — |
| `agent` | dueño | lee | lee y escribe |

- **`vectoredit_migrator`** es el dueño de los esquemas y de todas las tablas, y el único que puede crear
  o cambiar tablas. Lo usa Alembic y ninguna aplicación en marcha: `alembic/env.py` hace `SET ROLE` a él antes
  de migrar, así toda tabla nueva tiene el mismo dueño.
- **`vectoredit_platform`** es la app de este repo.
- **`vectoredit_agent`** es el agente. Los cupos los cambia solo con funciones SQL autorizadas (VEC-30), y los
  créditos con las de VEC-47.
  En `auth` solo lee `users` y `sessions`, lo justo para validar la sesión con `auth.find_session()`: nunca ve
  contraseñas ni enlaces de correo. Si el agente necesita otra tabla de `auth`, se le da en una migración nueva, tabla por tabla.

Excepciones por tabla de las migraciones `0013` y `0015`, cubiertas por las pruebas de seguridad.

| Tabla | Excepción |
|---|---|
| `agent.period_quotas` | El agente solo la lee. La plataforma además inserta y actualiza: asigna los cupos según el plan |
| `agent.reservations` | El agente solo la lee: reserva y libera con las funciones de cupos |
| `agent.rates` | El agente solo la lee. La plataforma además inserta: un precio nuevo es una fila nueva, nunca se cambia uno viejo |
| `agent.usage` | El agente inserta pero no cambia ni borra: es contabilidad |
| `operations.audit_log` | Nadie lo cambia ni lo borra: solo se agregan entradas |
| `billing.plan_entitlements` | La plataforma lee y agrega versiones de derechos |
| `billing.credit_balances` | La plataforma puede abrir un saldo y cambiar el total. El contador reservado solo cambia con las funciones |
| `billing.credit_movements` | La plataforma lee y agrega movimientos. Solo la función de liquidación agrega débitos `agent_usage` |
| `billing.credit_reservations` | La plataforma solo lee. Las funciones crean y liquidan reservas |

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

### Tablas con RLS

| Tablas | Una sesión ve | Migración |
|---|---|---|
| `platform.accounts` | su cuenta (o, al iniciar sesión, la del usuario conectado) | `0010` |
| `platform.workspaces` | los espacios de su cuenta (`owner_id`) | `0012` |
| `platform.folders`, `documents`, `document_revisions`, `revision_images`, `document_versions`, `share_links` | las filas de sus espacios (`workspace_id`) | `0012` |
| `storage.objects`, `uploads`, `saves`, `workspace_quotas`, `byte_reservations` | las filas de sus espacios (`workspace_id`) | `0012` |
| `agent.conversations`, `runs` | las de su cuenta (`account_id`) en sus espacios | `0013` |
| `agent.messages` | las de las conversaciones de su cuenta | `0013` |
| `agent.pending_calls`, `usage` | las de las ejecuciones de su cuenta | `0013` |
| `agent.period_quotas`, `reservations` | las de su cuenta (`account_id`) | `0013` |
| `operations.object_copies` | las copias de los archivos de sus espacios | `0013` |
| `operations.audit_log` | lee las entradas de sus espacios. Una sesión **sin cuenta** puede agregar una en cualquier espacio; **con cuenta**, solo en los suyos (o sin espacio) | `0013` |
| `billing.subscriptions`, `credit_balances`, `credit_movements`, `credit_reservations` | las filas de su cuenta | `0015` |

Los catálogos `billing.plans`, `billing.plan_entitlements`, `billing.credit_packs` y `agent.rates`
son globales, igual que `operations.backup_runs`. `billing.gateway_events` también es global
porque recibe eventos antes de identificar una cuenta. Solo la plataforma y el migrador acceden
a su contenido.

**`operations.audit_log` se escribe con `db.execute(insert(AuditEntry).values(...))`, nunca con `db.add()`.**
Una entrada se puede agregar sin cuenta fijada (un inicio de sesión fallido, un enlace compartido abierto sin
sesión), pero esa sesión no puede leerla, y PostgreSQL trata `RETURNING` como una lectura. Por eso la tabla no
pide `RETURNING` sola (`implicit_returning=False`), y `db.add()` falla, porque necesita el id nuevo.

Todas con `FORCE`. Las columnas que registran quién hizo algo (`storage.uploads.account_id`,
`storage.saves.account_id` y `platform.document_revisions.author_account_id`) también se revisan al escribir:
tienen que ser la cuenta de la sesión (el autor de una revisión puede quedar vacío). Así nadie registra una
acción a nombre de otra cuenta.

Tres pruebas de `tests/test_database_security.py` cuidan que no falte ninguna:

- `test_every_table_with_account_data_has_forced_rls`: toda tabla de `platform`, `storage`, `billing`, `agent`
  y `operations` tiene que tener RLS forzada y una política. Si una tabla de esos esquemas de verdad no tiene
  datos de una cuenta (como `agent.rates`), se agrega a `TABLES_WITHOUT_ACCOUNT_DATA` con el motivo.
- `test_every_workspace_table_is_tested`: toda tabla con `workspace_id` tiene que estar en `WORKSPACE_TABLES`,
  así recibe las pruebas de aislamiento (y una fila en `_fill_workspace`). Si sigue otras reglas (como
  `operations.audit_log`), va en `WORKSPACE_TABLES_TESTED_ELSEWHERE` y se prueba aparte.
- `test_every_account_column_is_tested`: toda columna que apunta a `platform.accounts` tiene que estar en
  `ACTOR_COLUMNS` (quién hizo algo) o en `OWNER_COLUMNS` (de quién es la fila), así se prueba que nadie la
  escribe a nombre de otra cuenta.

Las tablas del agente que siguen a su padre o a la cuenta (`messages`, `pending_calls`, `usage`,
`period_quotas`, `reservations`) y `operations.object_copies` se prueban en `tests/test_agent_security.py`,
con una tabla de qué rol puede leer, insertar, cambiar y borrar cada una (`READERS`, `INSERTERS`, ...).

Lo que RLS deja afuera **a propósito**, y que necesitará su propio camino cuando llegue. Una función
`SECURITY DEFINER` sola no alcanza, porque con `FORCE` las políticas también filtran al migrador (ver
[Funciones](#funciones)). Hará falta una política o un rol pensados para ese caso, y se decide en su tarea:

- **Abrir un enlace compartido** sin sesión: quien lo abre no tiene cuenta, así que no ve `platform.share_links`
  ni el documento. Lo que se agregue tiene que buscar el enlace por el hash del token y devolver solo lo que el
  enlace permite.
- **Tareas de limpieza** que recorren todas las cuentas (subidas, reservas y llamadas vencidas, verificación de
  copias): sin cuenta fijada no ven nada.

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

Si la tabla tiene `workspace_id`, se compara con los espacios de la cuenta, como en la migración `0012`:

```sql
CREATE POLICY account_isolation ON storage.uploads
    USING (workspace_id IN (SELECT w.id FROM platform.workspaces w
                            WHERE w.owner_id = platform.current_account_id()))
    WITH CHECK (workspace_id IN (SELECT w.id FROM platform.workspaces w
                                 WHERE w.owner_id = platform.current_account_id()))
```

Agrega la tabla a `WORKSPACE_TABLES` y una fila suya a `_fill_workspace` en `tests/test_database_security.py`:
así corre todas las pruebas de aislamiento (leer, cambiar, borrar, mover e insertar en otro espacio, con
cada rol que tiene acceso).

- `USING` filtra lo que se lee, actualiza y borra; `WITH CHECK` impide escribir filas de otra cuenta.
- `FORCE` hace que el dueño (el migrador) también quede filtrado. Solo los superusuarios se saltan RLS.
  Por eso **las pruebas de seguridad no corren como superusuario**: cambian al rol con `SET LOCAL ROLE`
  (ver `tests/test_database_security.py`). Agrega ahí la prueba de tu tabla.
- Una migración de datos que tenga que tocar filas de todas las cuentas corre como superusuario, o desactiva
  `FORCE` en esa migración y lo vuelve a activar al final.
- El agente solo escribe cupos y créditos mediante funciones autorizadas. La migración `0013` quita
  los permisos de escritura directa para las tablas de cupos. En `billing`, la migración `0015` concede
  uso del esquema y ejecución de las funciones de créditos. Las tablas de `billing` conservan sus
  permisos exclusivos de plataforma y migrador.

### Funciones

Las funciones que crea el migrador **no las puede ejecutar nadie** hasta que la migración que las crea lo
permita (`ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, migración `0010`). Por eso
cada función nueva lleva su `GRANT EXECUTE` a los roles que la usan:

```sql
CREATE FUNCTION billing.reserve_credits(...) RETURNS ...
    LANGUAGE plpgsql
    SECURITY DEFINER                     -- corre con los permisos del migrador
    SET search_path = pg_catalog, pg_temp
AS $$ ... $$;
GRANT EXECUTE ON FUNCTION billing.reserve_credits(...) TO vectoredit_agent;
```

- `SECURITY DEFINER` da **permisos**: la función escribe donde el que la llama no puede (por ejemplo, el agente
  en `agent.period_quotas`). **No se salta la RLS**: las tablas usan `FORCE`, así que las políticas también
  filtran al migrador, con la cuenta fijada por la sesión que llama. Una función así solo ve las filas de esa
  cuenta.
- Aun así, la función exige que haya cuenta fijada (`platform.current_account_id()` no nulo) y nunca confía en
  un `account_id` que le pasen.
- Siempre con `SET search_path = pg_catalog, pg_temp` y nombres completos (`billing.credit_balances`), para
  que nadie pueda colarle una tabla o función con el mismo nombre.
  `test_every_security_definer_function_fixes_its_search_path` falla si una función no lo cumple.
- Una tarea que de verdad tenga que recorrer todas las cuentas (limpiezas) no puede apoyarse en esto: sin
  cuenta fijada no ve nada. Necesita un rol o una política propios, y se decide con esa tarea.

### Funciones de cupos

Migración `0014`. Son la **única** forma en que el agente cambia `agent.period_quotas` y `agent.reservations`.
Validan saldo y límites en la misma operación que los cambian, con la fila del cupo bloqueada (`FOR UPDATE`),
así dos ejecuciones que reservan a la vez se revisan una después de la otra y no pasan juntas el cupo.

| Función | Qué hace |
|---|---|
| `agent.reserve_quota(run_id, resource, amount, expires_at) → uuid` | Reserva `amount` del cupo vigente de la cuenta para una ejecución activa. Devuelve el id de la reserva |
| `agent.settle_reservation(reservation_id, used)` | Pasa `used` (entre 0 y lo reservado) a `consumed` y devuelve el resto |
| `agent.release_reservation(reservation_id)` | Devuelve todo lo reservado (la ejecución falló o se canceló) |

Las tres son **idempotentes**: repetir una llamada que ya tuvo efecto no cambia nada, así un reintento nunca
cobra dos veces. `reserve_quota` repetida con la misma ejecución y recurso devuelve la misma reserva (con otra
cantidad, falla). Eso vale también si el reintento llega mientras la primera llamada sigue en curso:
`reserve_quota` bloquea primero la ejecución, así el reintento espera y después encuentra la reserva. Solo las
puede ejecutar `vectoredit_agent`.

Desde el agente, dentro de la transacción en la que ya fijó la cuenta:

```sql
SELECT agent.reserve_quota($1, 'tokens', 4000, now() + interval '10 minutes');
SELECT agent.settle_reservation($1, 3120);
```

Errores, con su propio SQLSTATE para que el agente los distinga sin leer el mensaje:

| SQLSTATE | Cuándo |
|---|---|
| `VQ001` | No hay cuenta fijada en la transacción |
| `VQ002` | La ejecución no existe, no es de la cuenta o ya terminó |
| `VQ003` | La cuenta no tiene cupo vigente de ese recurso |
| `VQ004` | El cupo no alcanza |
| `VQ005` | La reserva no existe, no es de la cuenta, o ya se liquidó o liberó (según la llamada) |
| `23514` | Cantidad no positiva, o `used` fuera de 0..lo reservado |

Pendiente: liberar las reservas vencidas de ejecuciones que nunca terminaron. Es una tarea de mantenimiento que
recorre todas las cuentas (ver el punto anterior) y va con la cola de trabajos (VEC-36).

### Funciones de créditos

Solo `vectoredit_agent` tiene permiso de ejecución. Cada llamada requiere la cuenta fijada en la
transacción. PostgreSQL bloquea la fila del saldo mientras reserva, y la fila de la reserva mientras
liquida. El saldo, la reserva y el movimiento se actualizan juntos dentro de la transacción.

- `billing.reserve_credits(run_id uuid, amount bigint, expires_at timestamptz) -> uuid` reserva hasta
  `balance - reserved` para una ejecución activa de esa cuenta. Reintentar con la misma ejecución y
  cantidad devuelve el mismo ID y conserva el vencimiento original.
- `billing.settle_credits(reservation_id uuid, used bigint) -> void` descuenta el uso real, libera todo
  lo reservado y escribe un movimiento `agent_usage` con el ID de la reserva como referencia. Usar
  cero devuelve todos los créditos y marca la reserva como `released`. Repetir la misma liquidación
  no vuelve a descontar. La caducidad identifica reservas para el trabajo de mantenimiento de VEC-36.

| SQLSTATE | Motivo |
|---|---|
| `VC001` | Falta la cuenta de la sesión |
| `VC002` | La ejecución o reserva no está disponible para esa cuenta |
| `VC003` | Saldo disponible insuficiente o inexistente |
| `VC004` | Cantidad, consumo o vencimiento inválidos |
| `VC005` | El reintento contradice una reserva o liquidación anterior |
| `VC006` | El saldo reservado no coincide con la reserva |

## Pruebas contra la base

Las reglas de la base (CHECK, UQ, FK) se prueban contra PostgreSQL con el fixture `db` de `tests/conftest.py`:
cada prueba corre dentro de una transacción que se deshace al final, así que no deja datos.
Ejemplos: `tests/test_auth_tables.py`, `tests/test_document_tables.py` y `tests/test_storage_tables.py`.
Para crear filas de prueba (cuenta, espacio, archivo, documento, revisión) usa `tests/factories.py`
en lugar de repetirlas. Necesitan la base migrada (`alembic upgrade head`).

Si dos ramas crean migraciones a la vez, mira «Trabajar en equipo con la base» en [desarrollo.md](desarrollo.md).
