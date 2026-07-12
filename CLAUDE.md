# Proyecto: Sistema de Predicción Brasileirão Série A

## Qué es esto
Sistema de IA para predecir resultados del Campeonato Brasileiro Série A (1X2, goles esperados, marcador probable, over/under, BTTS) con probabilidades calibradas y explicabilidad (SHAP). No es un scraper de estadísticas — es una plataforma de analítica deportiva con pipeline de datos, feature store, modelos y API.

El roadmap completo (fases y pasos) vive en `docs/plan_maestro.md`. Ese archivo es la fuente de verdad de qué sigue — no lo dupliques ni lo reescribas acá.

## Stack
- DB: PostgreSQL 16 (Docker) + SQLAlchemy + Alembic
- Backend: Python 3.12 + FastAPI + Pydantic v2
- Modelos: statsmodels (Poisson/Dixon-Coles) como baseline; LightGBM/XGBoost/CatBoost para clasificación; SHAP para explicabilidad
- Gestor de dependencias: uv
- Testing: pytest
- Entorno: Docker Compose, variables sensibles solo en `.env` (nunca hardcodeadas, nunca committeadas)

## Reglas no negociables

1. **Un paso a la vez.** Implementá únicamente lo que pide el prompt de programación actual. No adelantes trabajo de fases futuras aunque parezca obvio o rápido de agregar "ya que estás". Si ves algo que claramente hace falta después, dejá un comentario `# TODO(fase-X): ...` y seguí.
2. **Cero fuga de datos temporal (anti-leakage).** Cualquier dato usado para predecir el partido de la fecha N solo puede usar información disponible ANTES del kickoff de ese partido. Aplica especialmente a: cuotas (timestamp de captura, no de resultado), tabla de posiciones (recalculada a esa fecha, no la final), forma/ELO (solo partidos previos a esa fecha).
3. **Validación siempre walk-forward.** Entrenar con pasado, evaluar con futuro respecto a una fecha de corte. Split aleatorio de partidos está prohibido para evaluar modelos predictivos.
4. **Toda feature nueva se justifica con métrica, no con intuición.** Un feature de ingeniería avanzada (Fase 7+) solo entra al modelo final si mejora log-loss/Brier score en validación temporal contra el baseline. Si no mejora, se documenta como descartado, no se borra en silencio.
5. **Respetar límites de API.** football-data.org: 10 req/min. API-Football: 100 req/día. The Odds API: cuidado con el multiplicador markets×regions (500 créditos/mes). Todo cliente de API externa lleva rate limiting y cacheo en disco/DB — nunca volver a pedir un dato ya guardado.
6. **Secrets solo en `.env`**, nunca en código ni en commits. `.env.example` sirve de plantilla con claves vacías.
7. **Todo pipeline de datos lleva tests.** Un paso de ingesta/limpieza no está terminado sin al menos un test de caso feliz y uno de datos faltantes/corruptos.
8. **Si algo del prompt es ambiguo, preguntar antes de asumir** — en particular en decisiones de esquema de base de datos (caras de revertir) y en cualquier cosa que toque anti-leakage.

## Convenciones de código
- Type hints en todas las funciones públicas, docstrings estilo Google, PEP8 vía `ruff` (lint + format)
- Nombres de tabla en inglés, plural (`teams`, `matches`, `model_features`), consistentes con el esquema del plan maestro
- Un commit por paso atómico completado, mensaje descriptivo
- No agregar dependencias nuevas sin mencionarlo explícitamente en la respuesta

## Estructura de directorios (se crea en Fase 0)
```
/src
  /ingestion      # clientes de APIs externas
  /data           # limpieza, validación, esquema
  /features       # feature engineering
  /models         # entrenamiento, backtesting
  /api            # FastAPI
/tests
/docs
  plan_maestro.md
/alembic
docker-compose.yml
.env.example
```

## Cuándo parar y avisar
- Si un paso requiere una API key que no fue provista, avisar y detenerse (no simular datos falsos "para probar" sin decirlo explícitamente).
- Si un test de calidad de datos falla, no ajustarlo para que pase ni silenciarlo — reportarlo.
