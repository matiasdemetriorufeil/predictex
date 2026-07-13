# Progreso — Sistema de Predicción Brasileirão Série A

Última actualización: 2026-07-13
Referencia completa del plan: `docs/plan_maestro.md`

**Próximo paso: 2.4**

---

## Fase 0 — Fundamentos y entorno
- [x] 0.1 Estructura de repositorio + gestor de dependencias (uv)
- [x] 0.2 Docker Compose: PostgreSQL + configuración tipada de variables de entorno
- [x] 0.3 Logging y jerarquía de excepciones estándar del proyecto
- [x] 0.4 CI básico (GitHub Actions) corriendo pytest en cada push

## Fase 1 — Diseño de la base de datos (core) ✅ completa
- [x] 1.1 Esquema relacional core: Teams, Seasons, Venues, Matches, Season_Teams (`docs/schema_core.md`)
- [x] 1.2 Modelos ORM (SQLAlchemy) + migración inicial con Alembic (`src/data/models.py`, `alembic/versions/`)
- [x] 1.3 Script de validación del esquema (`src/data/schema_validation.py`, `uv run python -m src.data.schema_validation`)
  - Enmienda en 2.1: `teams.city`/`venues.city` pasaron a nullable y se agregó `teams.state`
    (migración incremental `8710345d53dc`), porque el dataset de bootstrap no trae ciudad exacta.

## Fase 2 — Ingesta de datos históricos (bootstrap)
- [x] 2.1 Importación de dataset histórico desde GitHub (`adaoduque/Brasileirao_Dataset`,
      `src/ingestion/bootstrap_historical.py`) — 22 temporadas (2003-2024), 45 equipos,
      167 venues, 8782 partidos cargados contra la base real.
- [x] 2.2 Cliente API football-data.org (`src/ingestion/football_data_client.py`,
      `football_data_mapper.py`) — temporadas 2025 (380 partidos, finished) y 2026 (380
      partidos: 177 finished, 202 scheduled, 1 postponed) cargadas. No persiste standings
      (anti-leakage). 24 equipos nuevos sin match de nombre (20 en 2025, 4 nuevos en 2026 -
      promovidos), a reconciliar en 2.4.
- [x] 2.3 Cliente API-Football (`src/ingestion/api_football_client.py`, `api_football_ingest.py`)
      — SOLO team stats agregadas (lineups por fixture explícitamente fuera de alcance,
      evaluar en/después de Fase 6). league_id=71 confirmado con llamada real. Cobertura
      real limitada por el plan free a 2023-2024 (2025/2026 rechazados por la API) — queda
      documentado en `docs/schema_core.md` como hueco a evaluar tras Fase 6. 40 stats
      cargadas (20 equipos × 2 temporadas), 5 equipos nuevos sin match, a sumar a 2.4.
- [ ] 2.4 Normalización de nombres/IDs de equipos entre fuentes (acumulado: 24 de
      football-data.org + 5 de API-Football = 29 equipos a reconciliar)
- [ ] 2.5 Script de ingesta incremental (partidos nuevos, programable)

## Fase 3 — Datos complementarios de bajo costo
- [ ] 3.1 Cliente OpenWeatherMap (clima por partido)
- [ ] 3.2 Cliente Google Maps Distance Matrix (distancias, con caché)
- [ ] 3.3 Cálculo de contexto/motivación (tabla, descenso, Libertadores)
- [ ] 3.4 Cliente The Odds API (cuotas de cierre, anti-leakage)

## Fase 4 — Limpieza y validación de datos
- [ ] 4.1 Pipeline de integridad (duplicados, nulos, inconsistencias)
- [ ] 4.2 Estrategia de datos faltantes (documentada)
- [ ] 4.3 Tests automatizados de calidad de datos

## Fase 5 — Feature engineering baseline
- [ ] 5.1 ELO rating ajustado por localía
- [ ] 5.2 Forma reciente (últimos 3/5/10, local/visitante)
- [ ] 5.3 Descanso y fatiga (días entre partidos, viajes)
- [ ] 5.4 Tabla `ModelFeatures` versionada

## Fase 6 — Modelo baseline
- [ ] 6.1 Modelo Dixon-Coles / Poisson bivariado
- [ ] 6.2 Framework de walk-forward validation
- [ ] 6.3 Métricas: log-loss, Brier score, calibración, benchmark vs mercado
- [ ] 6.4 Backtesting histórico completo

## Fase 7 — Modelos avanzados y ensemble
- [ ] 7.1 Features avanzadas propias (validadas contra baseline)
- [ ] 7.2 Modelo de clasificación (LightGBM/XGBoost) para 1X2
- [ ] 7.3 Análisis SHAP y poda de variables
- [ ] 7.4 Ensemble (stacking): Poisson + LightGBM + ELO
- [ ] 7.5 Calibración final de probabilidades

## Fase 8 — Simulación y mercados adicionales
- [ ] 8.1 Simulación Monte Carlo (marcador exacto, over/under, BTTS)
- [ ] 8.2 Intervalos de confianza / incertidumbre

## Fase 9 — API del sistema
- [ ] 9.1 API REST con FastAPI (endpoints de predicción)
- [ ] 9.2 Endpoint de explicación (SHAP por partido)
- [ ] 9.3 Documentación automática (OpenAPI/Swagger)
- [ ] 9.4 Autenticación básica / rate limiting

## Fase 10 — Automatización y monitoreo (MLOps ligero)
- [ ] 10.1 Scheduler de ingesta y recálculo de features
- [ ] 10.2 Reentrenamiento periódico + versionado de modelos (MLflow)
- [ ] 10.3 Monitoreo de performance en producción (drift, calibración)

## Fase 11 — Frontend (opcional, futuro)
- [ ] 11.1 Dashboard simple (Streamlit) de predicciones
- [ ] 11.2 Historial de predicciones vs resultados reales