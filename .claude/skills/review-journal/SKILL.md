---
name: review-journal
description: Revisa el diario de decisiones del bot (data/journal.jsonl, papel o Binance Demo) contra los umbrales de research/PROTOCOLO-DEMO.md, mide los vetos de Jev en modo sombra y propone cambios como diff para aprobación humana. Usar para la revisión semanal o cuando el usuario pregunte cómo viene el bot.
---

# Revisión del diario (System Two sobre System One)

Jev decide rápido; Claude revisa despacio. Esta skill NUNCA cambia parámetros en caliente. Durante la prueba en
Demo Mode, los umbrales son los de `research/PROTOCOLO-DEMO.md`, decididos antes de empezar: no se reinterpretan.
Apoyate en las skills `live-vs-backtest-drift-monitoring` y `paper-trading-and-forward-test-protocol`.

1. Leé `data/journal.jsonl` y el estado (`data/binance_demo_state.json` o `data/paper_account.json`). No leas `.env`.
   El estado tiene `symbols`, `capital`, `realized` por moneda y `positions` (con `risk` = 1 R en dólares).
2. Calculá con un script Python corto, no a ojo:
   - **Fase 1:** días con registro, eventos `error`, `error_orden`, `abortada_sin_stop`, `prueba_ida_y_vuelta`
     (ok o no), y en cada `entrada` el deslizamiento: precio de entrada contra `close`.
   - **Fase 2:** cada trade cerrado en R (campo `r` de los eventos `salida`; 1 R = 1 % de la bolsa de esa moneda), la suma de R, la caída máxima en R y el
     número de trades. Compará contra la tabla del protocolo (13,8 R / 17,9 R / −6,2 R a los 30 trades) y decí qué
     acción corresponde.
   - **Jev en sombra:** en las entradas con `shadow`, compará el R medio de las que Jev habría vetado contra el de las
     que habría aprobado. Avisá si el juez fue MockJev (`model` contiene "NO es Jev"): en ese caso no mide nada.
   - **Calibración:** agrupá por `answers.regime.confidence` en bandas (0–0,4, 0,4–0,7, 0,7–1) y compará resultados.
   - Errores de API y latencias altas (`latency_ms`).
3. Escribí `reports/review-YYYY-MM-DD.md` con:
   - un resumen de 5 líneas;
   - la tabla del protocolo con el estado (pasa, alerta o falla);
   - los hallazgos;
   - como mucho 3 propuestas, cada una con el backtest que la respalda (skill `backtest`).
4. Las propuestas van como diff en el reporte o en una rama/PR. No las apliques a `main` ni toques `LIVE_TRADING`.
   Recordá que cambiar una regla reinicia la prueba.
