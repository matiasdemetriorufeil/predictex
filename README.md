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

## Validar el esquema

Antes de arrancar la ingesta de datos (Fase 2), corré el chequeo de salud del esquema contra
la base configurada en `.env`:

```
uv run python -m src.data.schema_validation
```

Verifica contra `information_schema` (no contra la metadata de los modelos) que las 7 tablas
core existen, que las foreign keys apuntan a donde corresponde, que los constraints únicos y
el `CHECK` de `matches` están presentes, y que la nullability de las columnas coincide con
`docs/schema_core.md`. Termina con exit code `0` si todo pasa, `1` si algo falla.

## CI

En cada `push` y pull request, GitHub Actions (`.github/workflows/ci.yml`) corre dos jobs:

- **lint-and-test**: `ruff check .` y `pytest -m "not integration"` (tests unitarios, sin Postgres).
- **integration-test**: levanta un servicio de PostgreSQL 16 nativo del workflow (con healthcheck) y corre
  `pytest -m integration` contra esa base real.
