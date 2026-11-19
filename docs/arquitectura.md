# Arquitectura

## Dónde encaja este backend

VectorEdit tiene tres piezas:

| Pieza | Repo | Lenguaje | Qué hace |
|---|---|---|---|
| Editor | `vector_de_imagen` | Vue + TypeScript | La aplicación en el navegador: lienzo, herramientas, render. |
| **Plataforma** | **este repo** | **Python (FastAPI)** | **Cuentas, documentos, archivos, cuotas, cobro y mantenimiento.** |
| Agente | servicio aparte | TypeScript | El agente de diseño: conversaciones, ejecuciones y consumo. |

Plataforma y agente comparten una sola base PostgreSQL, pero cada uno entra con su propio rol y
sus propias credenciales. **Las tablas y migraciones se definen solo aquí**, con SQLAlchemy y Alembic.
El agente las lee con su rol y no migra nada.

Los archivos pesados (el JSON del diseño y las imágenes) no van en la base: van a un bucket S3 privado.
El navegador sube y baja archivos directo al bucket con URLs firmadas que caducan en 10 minutos como máximo.

La base tiene seis esquemas, definidos en `Modelo_relacional_VectorEdit` (allí con nombres en español);
la migración `0002` los crea vacíos; las tablas llegan con VEC-29 (`auth`, `platform`, `storage`) y VEC-41 (`agent`, `operations`), VEC-47 (`billing`) y VEC-36 (`operations.jobs`). Cómo escribirlas: [base-de-datos.md](base-de-datos.md).

| Esquema | Módulo que lo maneja |
|---|---|
| `auth` | `app/auth/` |
| `platform` | `app/documents/` |
| `storage` | `app/storage/` |
| `billing` | `app/billing/` |
| `agent` | `app/agent/` (solo tablas: las escribe el servicio del agente, aquí solo se definen y migran) |
| `operations` | `app/jobs/` y procesos de mantenimiento |

## Módulos

El código se ordena por tema del negocio, no por tipo de archivo. Cada tema es una carpeta con todo lo suyo.

| Módulo | Para qué sirve | Tareas |
|---|---|---|
| `core/` | Lo común a todos: configuración (`config.py`), conexión a la base (`db.py`), base y columnas comunes de las tablas (`model_base.py`), registro de modelos para Alembic (`models_registry.py`) y metadatos de Swagger (`openapi.py`). | VEC-3, VEC-29 |
| `health/` | `GET /api/v1/health` responde `{"status": "ok"}`. Sirve para comprobar que el servidor está vivo. | VEC-3 |
| `auth/` | Inicio de sesión (enlace por correo y Google) y sesión con cookie; la primera vez crea la cuenta. Expone `get_current_user` para que los demás módulos sepan quién llama. El agente valida la sesión que emite este módulo. | VEC-4, VEC-40 |
| `documents/` | La ficha de cada documento y sus permisos: crear, abrir, guardar sin perder ni pisar cambios, versiones, carpetas, papelera y compartir. | VEC-29, 31, 42, 43 |
| `storage/` | Los bytes: cliente S3, URLs firmadas, validación de lo subido y cuotas de espacio. Es el único módulo que habla con S3. | VEC-29, 31, 42 |
| `billing/` | Planes, pagos, suscripciones y créditos que reserva el agente. Llega después del lanzamiento. | VEC-33, VEC-47 |
| `agent/` | Solo las tablas del esquema `agent`. Las escribe el servicio del agente (TypeScript); aquí se definen para que Alembic siga siendo el único que migra. Sin rutas ni lógica. | VEC-41 |
| `jobs/` | Cola de mantenimiento en PostgreSQL. Un proceso separado de la misma aplicación reclama trabajos y llama a los servicios que poseen los datos. | VEC-36 |

### Documents y storage: en qué se diferencian

- `documents/` decide **qué** se guarda y **quién** puede verlo. Vive en tablas.
- `storage/` decide **dónde quedan los bytes** y si caben en el cupo. Vive en tablas + bucket.

Storage no sabe nada de carpetas ni versiones; solo de archivos y cupos. Así, cambiar de proveedor de almacenamiento
solo toca `storage/`.

## Carpetas de cada módulo

Cada módulo tiene una carpeta por capa, y dentro **un archivo por tema**. El `__init__.py` de cada carpeta
importa lo público, así el resto del código importa siempre igual (`from app.auth.models import AuthUser`)
aunque la carpeta crezca.

```text
app/auth/
├── __init__.py
├── router/              # rutas HTTP
│   ├── __init__.py      # crea el router del módulo e incluye los de cada archivo
│   └── sessions.py      # un archivo por grupo de rutas
├── schemas/             # entrada y salida (Pydantic)
│   ├── __init__.py
│   └── session.py       # un archivo por tema
├── service/             # lógica de negocio
│   ├── __init__.py
│   └── email_links.py   # un archivo por caso de uso
└── models/              # tablas
    ├── __init__.py      # importa todas las tablas del módulo
    ├── user.py          # un archivo por tabla
    └── session.py
```

| Carpeta | Qué contiene | Qué no contiene |
|---|---|---|
| `router/` | Rutas HTTP. Recibe la petición, la valida con `schemas` y llama a `service`. | Consultas a la base, reglas de negocio. |
| `schemas/` | Modelos Pydantic de entrada y salida. Es lo que aparece en Swagger. | Tablas. |
| `service/` | Lógica de negocio, permisos y transacciones. | Detalles HTTP (status, headers). |
| `models/` | Tablas SQLAlchemy del esquema del módulo. | Lógica. |

`jobs/` solo tiene `service/` y `models/`, porque no recibe peticiones HTTP; `agent/` solo tiene `models/`.
Cada `__init__.py` empieza con un comentario que dice qué va en esa carpeta y cómo dividirla.
Ejemplos ya hechos: `app/auth/models/` (una tabla por archivo) y `app/health/router/` (rutas incluidas).

## Cómo se comunican

```text
navegador ─HTTP─> router/ ─> service/ ─> models/ ─> PostgreSQL
                     │              │
                schemas/          └─> storage/service/ ─> almacenamiento S3
```

1. El router no toca la base; llama al service.
2. Un módulo usa a otro **a través de su `service`** (`from app.storage.service import ...`), nunca leyendo sus tablas.
3. Solo `storage/` habla con S3.
4. Lo compartido va en `core/`.

## Ejemplo completo: guardar un documento (VEC-31)

Tres llamadas del editor (`documents/router/saves.py`); la lógica está en `documents/service/save.py` y la
parte de archivos y cupo en `storage/service/`.

1. **Preparar** (`POST /documents/{id}/saves`): el editor manda la revisión base, una clave de idempotencia y
   la descripción de cada archivo (hash, tamaño, tipo, dimensiones). `documents/` comprueba que el documento
   es de la cuenta y que la revisión base es la actual (si no, **409**). `storage/` bloquea el cupo, reserva
   los bytes (si no caben, **507**), registra el guardado con lo declarado y devuelve una URL firmada por
   archivo (10 minutos como máximo). Las imágenes que ya están en el espacio no se vuelven a subir.
2. **Subir**: el navegador sube cada archivo directo al bucket, a una clave temporal (`uploads/...`). La firma
   incluye tamaño y tipo, así que el almacenamiento rechaza otro cuerpo.
3. **Confirmar** (`POST /documents/{id}/saves/{save_id}/commit`): `storage/` lee cada archivo una vez, revisa
   tamaño, hash, gzip y JSON o formato y dimensiones de imagen **leyendo los bytes**, y escribe esos mismos
   bytes en su clave definitiva (`objects/...`), que ya no cambia. Después, en una transacción corta,
   `documents/` bloquea cupo, documento y archivos en ese orden, comprueba otra vez la revisión base, crea la
   revisión con su mapa de imágenes y la marca como actual. Solo una respuesta `confirmed` significa
   «guardado».

| Situación | Qué pasa |
|---|---|
| Se pierde una respuesta | Repetir con la misma clave devuelve el mismo guardado (200), confirmado si ya lo estaba. La misma clave con otro contenido: **422**. |
| Otro dispositivo guardó antes | **409** con la revisión actual; el guardado queda en `conflict` y nunca pisa nada. |
| Falta subir un archivo | **422**; el guardado sigue abierto: se sube y se confirma otra vez. `GET .../saves/{save_id}` devuelve URLs nuevas para lo que falta. |
| Un archivo no es lo declarado | **422**; el guardado se cancela y libera su reserva. Hay que empezar otro. |
| Dos confirmaciones a la vez | Cada archivo lo revisa una sola (con un plazo de 5 minutos); la otra responde `preparing` y el editor vuelve a preguntar. |
| Pasan 30 minutos sin confirmar | **410**; la reserva se libera y sigue valiendo la revisión anterior. |
| Falla la transacción | Los archivos ya guardados quedan sin uso (`unreferenced_since`) y se borran días después. |

Una imagen se guarda una sola vez por espacio, aunque la usen muchas revisiones (índice único por hash).

Más tarde, la cola de `jobs/` llama a `storage.service`: `expire_uploads_and_reservations` caduca los
guardados vencidos y libera su espacio; `delete_unused_objects` borra los archivos sin uso hace más de 8 días
en dos pasadas (primero los marca `pending_deletion`, en la siguiente borra los bytes), para que un fallo
nunca deje un archivo `ready` sin bytes; `reconcile_storage_quotas` recalcula el cupo.

## Abrir un documento y restaurar una versión (VEC-42)

**Abrir** (`GET /documents/{id}/content`, `documents/service/open.py`): comprueba que el documento es de la
cuenta (si no, **404** y ninguna URL) y devuelve una URL firmada de un solo `GET` por archivo de la revisión
actual (JSON, miniatura e imágenes), válida 10 minutos como máximo. Cuando caducan, el editor vuelve a pedir.
También devuelve `account_id` y `workspace_id`, para que el editor separe su caché sin red por cuenta. Un
borrador nunca guardado responde sin archivos (`revision: null`).

**Restaurar** (`POST /documents/{id}/versions/{version_id}/restore`, `documents/service/versions.py`):
publica la revisión de la versión como la **siguiente** revisión, con los mismos archivos (no se copian
bytes). El número siempre sube: restaurar la 3 con la 7 vigente crea la 8. La revisión que estaba vigente se
guarda como versión `restore` (`undo_version_id`), así que restaurarla deshace la restauración. Pide la
revisión que el editor tiene en pantalla: si otra se guardó mientras tanto, **409** y no cambia nada.

Guardar y restaurar publican con la misma función (`documents/service/revisions.py`), con el mismo orden de
bloqueo: cupo, documento, archivos.

## Inicio de sesión y sesiones (VEC-4)

Dos formas de entrar, las dos sin contraseña. La primera vez se crean el usuario (`auth.users`) y su cuenta
(`platform.accounts`). Sesiones, enlaces y usuarios son código propio; Authlib solo hace el ida y vuelta con
Google (VEC-40).

| Ruta (`/api/v1/auth/...`) | Qué hace |
|---|---|
| `POST /email-links` | Manda un enlace de un solo uso que vence en 15 minutos. Responde lo mismo exista o no el correo. Máximo 3 por correo cada 15 minutos (429). |
| `POST /email-links/preview` | Dice de qué correo es un enlace **sin gastarlo**, para que el editor pida confirmación. Un enlace que no serviría para entrar responde 400. |
| `POST /sessions` | Recibe el `token` del enlace, lo gasta y crea la sesión (cookie). Un enlace usado, vencido o de otro propósito responde 400. Si el navegador ya tenía una sesión, la cierra. |
| `GET /sessions/current` | Quién está conectado. Sin sesión, 401. |
| `DELETE /sessions/current` | Cierra la sesión en la base y borra la cookie. |
| `DELETE /sessions` | Cierra todas las sesiones del usuario, en todos sus dispositivos. |
| `GET /google` | Redirige a Google. Se abre en el navegador, no con `fetch`. |
| `GET /google/callback` | Google vuelve aquí. Crea la sesión y redirige a `FRONTEND_URL`; si algo falla, a `FRONTEND_URL/sign-in?error=google`. |

**Enlace por correo.** El enlace es `FRONTEND_URL/sign-in/email#token=<token>`. El token va después de `#`
para que el navegador no lo mande a ningún servidor ni en el `Referer`. Esa página del editor manda el token
con `POST /sessions`: gastar el enlace cambia datos, así que no es un `GET`, y los antivirus de correo que
abren los enlaces no lo gastan.

**Google.** Flujo con código de autorización, PKCE y `state`, guardados en la cookie `vectoredit_google`
(10 minutos). Si Google no confirma que el correo está verificado, no se une a un usuario existente. Una
cuenta de Google ya enlazada entra aunque su correo haya cambiado.

**La sesión.** Cookie `vectoredit_session`, `HttpOnly`, `Secure` y `SameSite=Lax`. Vence tras 30 días sin
usarla; mientras se usa no vence nunca. En la base solo se guarda el SHA-256 del token. Volver a iniciar
sesión (con correo o Google) cierra la sesión que el navegador tenía.

**Renovación con rotación.** Si la sesión se usa más de una hora después de su última renovación, se alarga
otros 30 días **y se cambia el token**: la respuesta trae la cookie nueva y todas las pestañas del navegador
la usan enseguida (comparten cookies). El token anterior se sigue aceptando **2 minutos**, para las peticiones
que ya iban en camino. Si aparece después, la cookie fue copiada: solo una de las copias recibió el token
nuevo. Entonces la plataforma cierra la sesión: quien tenga la copia queda fuera y el usuario vuelve a
entrar. Si la respuesta con la cookie nueva se pierde (un corte de red justo en ese momento), pasa lo mismo:
el usuario vuelve a entrar. Es raro y falla del lado seguro. La cookie nueva la añade
`SessionCookieMiddleware` a cualquier respuesta, también si la ruta termina en error (404, 403, 500...) o
devuelve su propia respuesta.

**Peticiones de otros sitios (CSRF).** Toda petición `POST`, `PUT`, `PATCH` o `DELETE` debe traer un `Origin`
igual a `FRONTEND_URL` o `API_URL`; si no, 403 (`app/core/origin_check.py`). CORS solo permite al editor, con
credenciales.

**Para el editor.** Llamar a la API con `credentials: "include"`. Páginas que necesita:

- `/sign-in/email`: lee el token del `#`, lo borra de la barra con `history.replaceState` (así no queda en el
  historial ni se comparte copiando la URL), llama a `POST /email-links/preview` y pregunta «¿Entrar como
  ana@example.com?». Solo si el usuario confirma, hace `POST /sessions`. Sin esa confirmación, alguien
  podría mandar un enlace de **su** cuenta y el usuario entraría en ella sin darse cuenta, guardando ahí su
  trabajo.
- `/sign-in`: muestra el error de Google con `?error=google`.

**Para el agente.** Reconoce la misma cookie: calcula el SHA-256 del valor de `vectoredit_session` y llama a
`auth.find_session(<hash>)`, que devuelve `session_id`, `user_id` e `is_previous_token` (o nada si no vale).
No debe consultar `auth.sessions` a mano: la función es el único lugar con la regla (vencimiento, token
anterior y margen de 2 minutos), y la plataforma usa la misma. El agente no renueva ni rota: solo lee. Su
rol puede leer `auth.sessions` y `auth.users`, nada más de `auth`. Para recibir la cookie, el agente debe servirse en el mismo host que la API
o, si está en otro subdominio, `SESSION_COOKIE_DOMAIN` debe ser el dominio padre.

**Para los demás módulos.** Una ruta que necesita sesión declara `Depends(get_current_user)`
(`from app.auth.service import get_current_user`). Devuelve el usuario y su cuenta, y deja la sesión de la
base actuando por esa cuenta (`set_current_account`), así la seguridad por fila filtra todo lo demás.

## Referencias

- `Arquitectura_VectorEdit` y `Modelo_relacional_VectorEdit` (adjuntos en Jira, Epic VEC-28).
- Decisiones de identidad (VEC-40): Authlib solo para Google; sesiones y enlaces propios. Pendiente: el
  proveedor de correo.
