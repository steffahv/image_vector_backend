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

La base tendrá seis esquemas, definidos en `Modelo_relacional_VectorEdit`. Todavía no existen:
los crean las migraciones de VEC-29 (`auth`, `plataforma`, `almacenamiento`) y VEC-41 (`cobro`, `agente`, `operacion`).

| Esquema | Módulo que lo maneja |
|---|---|
| `auth` | `app/auth/` |
| `plataforma` | `app/documents/` |
| `almacenamiento` | `app/storage/` |
| `cobro` | `app/billing/` |
| `agente` | servicio del agente (aquí solo se migra) |
| `operacion` | `app/jobs/` y procesos de mantenimiento |

## Módulos

El código se ordena por tema del negocio, no por tipo de archivo. Cada tema es una carpeta con todo lo suyo.

| Módulo | Para qué sirve | Tareas |
|---|---|---|
| `core/` | Lo común a todos: configuración (`config.py`), conexión a la base (`db.py`), registro de modelos para Alembic (`models_registry.py`) y metadatos de Swagger (`openapi.py`). | VEC-3 |
| `health/` | `GET /api/v1/health` responde `{"status": "ok"}`. Sirve para comprobar que el servidor está vivo. | VEC-3 |
| `auth/` | Registro, inicio de sesión (correo y Google) y sesión con cookie. Expone `get_current_user` para que los demás módulos sepan quién llama. El agente valida la sesión que emite este módulo. | VEC-4, VEC-40 |
| `documents/` | La ficha de cada documento y sus permisos: crear, abrir, guardar sin perder ni pisar cambios, versiones, carpetas, papelera y compartir. | VEC-29, 31, 42, 43 |
| `storage/` | Los bytes: cliente S3, URLs firmadas, validación de lo subido y cuotas de espacio. Es el único módulo que habla con S3. | VEC-29, 31, 42 |
| `billing/` | Planes, pagos, suscripciones y créditos que reserva el agente. Llega después del lanzamiento. | VEC-33, VEC-41 |
| `jobs/` | Tareas que el backend hace solo: vaciar papelera vieja, podar versiones, borrar archivos sin uso, liberar cupos de guardados cortados. Corre como proceso aparte, sin Redis ni colas. | VEC-36 |

### Documents y storage: en qué se diferencian

- `documents/` decide **qué** se guarda y **quién** puede verlo. Vive en tablas.
- `storage/` decide **dónde quedan los bytes** y si caben en el cupo. Vive en tablas + bucket.

Storage no sabe nada de carpetas ni versiones; solo de archivos y cupos. Así, cambiar de proveedor de almacenamiento
solo toca `storage/`.

## Archivos de cada módulo

| Archivo | Qué contiene | Qué no contiene |
|---|---|---|
| `router.py` | Rutas HTTP. Recibe la petición, la valida con `schemas.py` y llama a `service.py`. | Consultas a la base, reglas de negocio. |
| `schemas.py` | Modelos Pydantic de entrada y salida. Es lo que aparece en Swagger. | Tablas. |
| `service.py` | Lógica de negocio, permisos y transacciones. | Detalles HTTP (status, headers). |
| `models.py` | Tablas SQLAlchemy del esquema del módulo. | Lógica. |

`jobs/` solo tiene `service.py`, porque no recibe peticiones HTTP.
Cada archivo empieza con un comentario que dice qué debe ir en él.

## Cómo se comunican

```text
navegador ─HTTP─> router.py ─> service.py ─> models.py ─> PostgreSQL
                     │              │
                schemas.py          └─> storage/service.py ─> almacenamiento S3
```

1. El router no toca la base; llama al service.
2. Un módulo usa a otro **a través de su `service.py`**, nunca leyendo sus tablas.
3. Solo `storage/` habla con S3.
4. Lo compartido va en `core/`.

## Ejemplo completo: guardar un documento

1. El editor pide a `documents/` guardar una revisión nueva, con la revisión base y una clave de idempotencia.
2. `documents/router.py` valida el cuerpo con `schemas.py` y llama a `documents/service.py`.
3. `documents/service.py` usa `auth/service.py` para saber quién llama y comprueba que sea dueño.
4. Pide a `storage/service.py` que reserve cupo y genere URLs firmadas.
5. El navegador sube los archivos directo al bucket con esas URLs.
6. `storage/service.py` valida lo subido (tamaño, formato, hash) y lo mueve a claves definitivas.
7. `documents/service.py` abre una transacción corta: bloquea cupo, documento y archivos en ese orden,
   comprueba que nadie guardó otra revisión, crea la revisión nueva y la marca como actual.
8. Si otro dispositivo guardó antes, responde **409** y no pisa nada.

Más tarde, `jobs/` libera el cupo si el guardado se cortó a la mitad y borra los archivos que quedaron sin uso.

## Referencias

- `Arquitectura_VectorEdit` y `Modelo_relacional_VectorEdit` (adjuntos en Jira, Epic VEC-28).
- Decisiones pendientes: librería de identidad en Python y contrato con el agente (VEC-40).
