# Skills de terceros

## Kryhr/26-quant-trading-skills

- Origen: https://github.com/Kryhr/26-quant-trading-skills (commit `d7eefaf1d2f000f80fb179fc9744a6b55dbd3cb4`)
- Licencia: MIT, Copyright (c) 2026 Kryhr. Ver `LICENSE-quant-skills-Kryhr`.
- Copiadas sin cambios. Son solo texto (SKILL.md y referencias), sin scripts. Se revisaron el 2026-10-11 antes de incorporarlas.
- Se copiaron 12 de 31 cuando el proyecto era un robot de trading. Al pasar a análisis de Polymarket quedaron
  las 5 que sirven para no confundir suerte con habilidad:
  - statistical-significance-and-deflated-metrics (corrección por mirar muchos traders a la vez)
  - overfitting-and-robustness-checks
  - monte-carlo-trade-resampling-and-drawdown-distribution
  - lookahead-bias-detection-methodology (no usar datos posteriores a la decisión, p. ej. en copiabilidad)
  - strategy-research-log-and-versioning (bitácora de hipótesis y escaneos)
- Están escritas para backtests de estrategias: acá se aplican sus ideas de estadística, no sus partes de ejecución.
- Algunas citan skills que no se copiaron. Esas están en el repo de origen.
- Si se actualizan, hay que volver a revisarlas antes de copiar la versión nueva.

## TypeSafe (oficial)

- No está copiada: se instala como plugin desde `typesafe-ai/skills`, según `.claude/settings.json` (`enabledPlugins`).
- Instalación manual: `claude plugin marketplace add typesafe-ai/skills` y después `claude plugin install typesafe@typesafe-ai`.
