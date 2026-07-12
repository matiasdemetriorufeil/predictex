# predictex

Sistema de predicción de resultados del Brasileirão Série A.

## Instalación

```
uv sync
```

## Cómo levantar el entorno

```
cp .env.example .env
# completar los valores en .env

docker compose up -d
uv sync
uv run pytest -m integration
```
