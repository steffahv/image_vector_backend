# Convenciones de código

## Idioma

- **Todo el código en inglés**: módulos, archivos, clases, funciones, variables, rutas, comentarios y docstrings.
- **La documentación en español** (`README.md` y `docs/`).
- Los esquemas de PostgreSQL conservan los nombres del modelo relacional:
  `auth`, `plataforma`, `almacenamiento`, `cobro`, `agente`, `operacion`.

## Nombres

| Qué | Estilo | Ejemplo |
|---|---|---|
| Módulos y archivos | `snake_case` | `documents/service.py` |
| Clases | `PascalCase` | `DocumentResponse` |
| Funciones y variables | `snake_case` | `get_current_user` |
| Constantes | `UPPER_SNAKE_CASE` | `API_PREFIX` |
| Rutas | `kebab-case`, sustantivos en plural | `/documents/{id}/revisions` |
| Schemas | sufijo según su uso | `DocumentCreate`, `DocumentUpdate`, `DocumentResponse` |

## Reglas de código

- **Tipos en todo.** mypy corre en modo estricto: sin `Any` sin motivo y sin `# type: ignore` sin explicación.
- **Reutilizar antes de escribir.** Busca si ya existe en `core/` o en el service de otro módulo.
  Extrae a una función cuando vayas a escribir algo por segunda vez, no antes.
- **Funciones cortas con un solo propósito.** Archivos de menos de ~600 líneas; si un módulo crece, divide su service.
- **Constantes con nombre** en vez de números sueltos (`SIGNED_URL_TTL_SECONDS = 600`).
- **Comentarios que explican el porqué**, no el qué. Sin código muerto ni código comentado.
- **Errores explícitos.** Nada de `except: pass`. El service lanza excepciones del dominio; el router las convierte en HTTP.
- **Sin credenciales en el código.** Todo valor sensible se lee con `get_settings()`.
- **Transacciones cortas** en el service, nunca en el router.

## Agregar una ruta

1. Define la entrada y la salida en `schemas.py`.
2. Escribe la lógica en `service.py`.
3. Agrega la ruta en `router.py` con `response_model` y `summary`.
4. Agrega su prueba en `tests/`.
5. Revisa que aparezca bien en `/docs`.

## Agregar un módulo

1. Crea `app/<module>/` con `__init__.py`, `router.py`, `schemas.py`, `service.py` y `models.py`.
   Cada archivo empieza con un docstring que dice qué va en él.
2. Registra el router en `app/main.py`.
3. Registra los modelos en `app/core/models_registry.py`.
4. Agrega su tag en `TAGS_METADATA` de `app/core/openapi.py`.
5. Documéntalo en `docs/arquitectura.md`.

## Ramas y PR

- Una rama por tarea de Jira: `feature/VEC-<n>-<descripcion>`. Así Jira la liga a la tarea.
- El PR debe pasar la CI y llevar una revisión antes de unirse a `main`.
