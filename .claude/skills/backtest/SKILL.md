---
name: backtest
description: Corre y evalúa backtests de Jev Trader con disciplina (tramo A para desarrollar, tramo B holdout intocable, comparación contra comprar-y-mantener y contra la estrategia sin Jev). Usar cuando el usuario pida probar una estrategia, un cambio de umbrales o una pregunta nueva de Jev.
---

# Backtest disciplinado

1. Corré los tests primero: `python3 -m unittest discover -s tests -t .`. Si fallan, no sigas.
2. Datos: preferí CSV cacheados en `data/` (`python3 -m jevtrader fetch --symbol X`). Usá al menos 3 activos
   (p. ej. BTCUSDT, ETHUSDT, SOLUSDT) para no sobreajustar a uno solo.
3. Corré: `python3 -m jevtrader backtest --csv data/X_1d.csv --report reports/X.html`.
   - Sin `TYPESAFE_API_KEY` el juez es MockJev. Decilo SIEMPRE en el resumen: esos números no miden a Jev.
   - Con API key, las respuestas quedan en `data/jev_cache.jsonl`: la segunda corrida es gratis y reproducible.
4. Reglas para sacar conclusiones:
   - Solo se ajustan parámetros mirando el tramo **A (desarrollo)**. El tramo **B (holdout)** se mira una vez al final.
     Si después de mirar B cambiás algo, B deja de ser holdout: decilo.
   - Comparar siempre tres filas: comprar-y-mantener, estrategia base, base + Jev. Jev "aporta" solo si mejora
     Sharpe y/o drawdown frente a la base **en B y en la mayoría de los activos**.
   - Mirá la sección "¿Ayudan los vetos?": si las señales vetadas rinden igual o mejor que las tomadas, el filtro
     está destruyendo valor aunque el drawdown baje.
   - Menos de ~30 trades por tramo = ruido. Decilo.
5. Resumí en una tabla corta (activo × variante × tramo B: retorno, maxDD, Sharpe, trades) y una recomendación
   concreta. No prometas rentabilidad futura.
