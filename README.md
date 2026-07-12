[![CI](https://github.com/matiasdemetriorufeil/predictex/actions/workflows/ci.yml/badge.svg)](https://github.com/matiasdemetriorufeil/predictex/actions/workflows/ci.yml)

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

## CI

En cada `push` y pull request, GitHub Actions (`.github/workflows/ci.yml`) corre dos jobs:

- **lint-and-test**: `ruff check .` y `pytest -m "not integration"` (tests unitarios, sin Postgres).
- **integration-test**: levanta un servicio de PostgreSQL 16 nativo del workflow (con healthcheck) y corre
  `pytest -m integration` contra esa base real.
