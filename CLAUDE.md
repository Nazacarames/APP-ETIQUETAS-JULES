# Jev Trader — guía para Claude Code

Robot de trading algorítmico en Python (solo librería estándar). Estrategia determinística genera
candidatos → Jev (TypeSafe AI, modelo "System One") los juzga con preguntas tipadas → el código aplica la
política y el riesgo → un broker ejecuta (papel por defecto).

Vos (Claude Code) sos el "System Two": investigás, escribís código, corrés backtests y revisás el diario.
Nunca estás en el camino caliente de una orden.

## Reglas no negociables
1. **Jev juzga, el código ejecuta.** Nada de aritmética, conteos ni fechas en preguntas a Jev: eso va en
   `features.py`. Jev nunca origina una operación; solo veta o achica las de la estrategia.
2. **Dinero real = decisión humana.** No toques `LIVE_TRADING`, no instancies brokers con `live=True`, no apuntes
   a `api.alpaca.markets`. Un hook (`.claude/hooks/guard_live.py`) lo bloquea igual.
3. **No leas `.env`.** Tiene API keys. Usá `.env.example` como referencia.
4. **Sin lookahead.** Señal con el cierre de la vela i, ejecución en la apertura de i+1. Si tocás `features.py` o
   `backtest.py`, `tests/test_features.py::TestNoLookahead` y `tests/test_backtest.py` tienen que seguir pasando.
5. **Holdout sagrado.** Ajustá parámetros mirando solo el tramo A. El tramo B se reporta, no se optimiza.
6. **Decí con qué juez corriste.** Si el backtest usó MockJev, los números no miden a Jev. Decilo siempre.
7. **El riesgo manda.** `risk.py` tiene la última palabra (1 % por trade, kill switch por drawdown y pérdida diaria).
   No aflojes límites sin pedido explícito del usuario.

## Comandos
```bash
python3 -m unittest discover -s tests -t .                      # tests (correr antes y después de cada cambio)
python3 -m jevtrader fetch --symbol BTCUSDT                      # velas diarias de Binance -> data/
python3 -m jevtrader backtest --csv data/BTCUSDT_1d.csv --report reports/BTC.html
python3 -m jevtrader paper --symbol BTCUSDT --once               # una vela en papel (para cron)
python3 -m jevtrader news --asset "Bitcoin (BTC)" --rss <url>    # triage de titulares
python3 -m jevtrader ping                                        # prueba la API de Jev
```

## Mapa del código
- `jevtrader/features.py` — indicadores causales y traducción a frases (state anónimo para Jev).
- `jevtrader/questions.py` — preguntas tipadas (noul/choice/score). Opción conservadora primero.
- `jevtrader/jev_client.py` — cliente HTTP de `/v1/systemone`, cache JSONL, self-consistency, MockJev.
- `jevtrader/judge.py` — política sobre las respuestas (umbrales en `config.GateConfig`), fail-closed.
- `jevtrader/strategy.py` — Donchian 20/10 + SMA200 + stop 2×ATR.
- `jevtrader/risk.py`, `broker.py`, `live.py`, `backtest.py`, `report.py`, `news.py`, `journal.py`.

## Skills del proyecto
- `/backtest` — evaluación disciplinada (A/B, tres variantes, análisis de vetos).
- `/review-journal` — revisión semanal del diario en papel; propone cambios como diff.
- `/jev-question` — agregar una pregunta nueva a Jev siguiendo las reglas de TypeSafe.
- Recomendado: skill oficial de TypeSafe (`claude plugin install typesafe@typesafe-ai`).
