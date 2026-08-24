# Image Vector Backend

Backend FastAPI para Image Vector WebApp.

## Estructura

```text
app/
├── main.py          # Punto de entrada FastAPI
├── api/             # Endpoints y routers
├── models/          # Modelos Pydantic
├── services/        # Logica de negocio
└── db/              # Configuracion de base de datos
tests/               # Pruebas con pytest
```

## Instalacion

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Desarrollo

```bash
uvicorn app.main:app --reload
```

La API queda disponible en `http://127.0.0.1:8000`. La documentacion interactiva
se encuentra en `/docs` y la comprobacion de salud en `/api/v1/health`.

Para ejecutar las pruebas:

```bash
pytest
```
