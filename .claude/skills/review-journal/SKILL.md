---
name: review-journal
description: Revisa el diario de decisiones del bot en papel (data/journal.jsonl), mide si los vetos y la confianza de Jev están calibrados y propone cambios como diff para aprobación humana. Usar para la revisión semanal o cuando el usuario pregunte cómo viene el bot.
---

# Revisión del diario (System Two sobre System One)

Jev decide rápido; Claude revisa despacio. Este skill NUNCA cambia parámetros en caliente.

1. Leé `data/journal.jsonl` y `data/paper_account.json` (no `.env`).
2. Calculá con un script Python corto (no a ojo):
   - Conteo de eventos: entrada, vetada, salida, bloqueado_por_riesgo, error.
   - Equity actual, máximo y drawdown.
   - Para cada entrada cerrada: P&L. Para cada veto: qué hizo el precio después (bajá las velas con
     `jevtrader.data.fetch_binance` y simulá con `jevtrader.backtest.shadow_trade`).
   - Calibración: agrupá decisiones por `answers.regime.confidence` en bandas (0–0.4, 0.4–0.7, 0.7–1) y compará
     el resultado medio por banda. Si mayor confianza no implica mejor resultado, la confianza no sirve como gate.
   - Errores de API / latencias altas (`latency_ms`).
3. Escribí `reports/review-YYYY-MM-DD.md` con: resumen en 5 líneas, tabla de números, hallazgos y como mucho
   3 propuestas concretas (umbral, pregunta nueva o cambio de estrategia), cada una con el backtest que la respalda
   (usá el skill `backtest`).
4. Las propuestas van como diff en el reporte o en una rama/PR. No las apliques a `main` ni toques `LIVE_TRADING`.
