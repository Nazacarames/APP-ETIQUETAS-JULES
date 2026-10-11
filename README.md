# Jev Trader

Robot de trading algorítmico que combina:

- **Una estrategia determinística**: seguimiento de tendencia Donchian 20/10 con filtro SMA200 y stop de 2×ATR. Es la que propone las entradas.
- **[Jev](https://docs.typesafe.ai) (TypeSafe AI) como juez**: no opera por su cuenta. Solo puede vetar una entrada o achicarla.
- **Gestión de riesgo en código**: riesgo de 1 % por operación y kill switches.
- **Claude Code como "System Two"**: investiga, escribe estrategias, corre backtests y revisa el diario de decisiones. Nunca está en el camino de una orden.

> ⚠️ **Modo papel por defecto. Proyecto educativo, no es asesoramiento financiero.** Los resultados de backtests son simulados y no garantizan nada.

---

## Qué es Jev (y qué no)

Jev salió en early access el 15/09/2026. No es un chatbot: recibe un **state** (texto o JSON) y **preguntas tipadas**, y devuelve probabilidades calibradas.

| Tipo | Devuelve | Ejemplo en este bot |
|---|---|---|
| `noul` | probabilidad de "sí" (0–1) | ¿El movimiento está sobreextendido? |
| `choice` | una opción de un conjunto cerrado + probabilidades + confianza | Régimen: disorderly / range_bound / trending_down / trending_up |
| `score` | posición en una escala ordenada + confianza | Calidad de la ruptura: débil / mixta / fuerte |

Según TypeSafe, la latencia es de 70–500 ms y el costo de US$ 0,042 por millón de tokens de entrada; la salida es gratis. En este bot cada consulta cuesta del orden de US$ 0,00002.

**Lo que la documentación oficial dice que Jev hace mal**: aritmética, contar, comparar números, ordenar fechas y estados largos con ruido. Además tiende a elegir la primera opción de un `choice`.

## Qué dice la evidencia (octubre 2026)

- **Predecir la dirección del precio no funcionó** en los backtests independientes publicados:
  - [egrm07/jev_bitcoin_backtest](https://github.com/egrm07/jev_bitcoin_backtest): AUC en holdout de 0,47 a 0,50 y Brier skill negativo en todas las representaciones. Todas las políticas perdieron después de costos (la mejor, −15,7 % frente a +25,6 % de comprar y mantener).
  - [TradeRank](https://www.traderank.ai/blog/what-is-jev-typesafe): 49 % de aciertos en dirección y un Brier peor que tirar una moneda. Su confianza seguía al momentum reciente.
- **Donde sí tiene sentido**: clasificar noticias (¿es sobre el activo?, ¿es material?, ¿es positiva o negativa?), etiquetar el régimen a partir de indicadores calculados en código, checks previos a una operación y auditar a otros modelos. Ver [apex-logic](https://www.apex-logic.net/news/jev-ai-model-for-trading-2026).
- **Proyectos de referencia**: [jarrodwatts/jev-trader](https://github.com/jarrodwatts/jev-trader), un market maker en Monad. Arranca en dry-run y su modelo por defecto es un mock. No publica rentabilidad.

**Por eso este bot no le pregunta a Jev "¿sube o baja?".** Le pide que juzgue un setup que ya generó el código. Además mide si ese juicio agrega valor: compara lo que habrían rendido las señales vetadas con las tomadas.

## Arquitectura

```
 Binance / CSV ──► features.py ──────────► strategy.py ──(¿señal?)──┐
 (velas OHLCV)     indicadores en código    Donchian + SMA200        │
                   + frases anónimas                                 ▼
                                                             judge.py ──► Jev /v1/systemone
 RSS noticias ──► news.py (triage) ─────────────────────────► (régimen, setup, sobreextensión,
                                                              riesgo de noticias) en 1 llamada
                                                                     │  probabilidades
                                                                     ▼
                                                 política en código: vetar / medio tamaño / completo
                                                                     │
                                                                     ▼
                                                 risk.py: 1 % por trade, tope por posición,
                                                 kill switch por DD y pérdida diaria
                                                                     │
                                                                     ▼
                                                 broker.py: PaperBroker (default) | Alpaca paper
                                                                     │
                                                                     ▼
                                                 journal.jsonl ──► Claude Code /review-journal
                                                                   (propone cambios, humano aprueba)
```

## Uso rápido

```bash
# Requiere Python 3.10+. No hay dependencias externas.
python3 -m unittest discover -s tests -t .           # 59 tests

python3 -m jevtrader backtest --synthetic --mock      # sin red, sin API key
python3 -m jevtrader fetch --symbol BTCUSDT           # baja velas diarias de Binance a data/
python3 -m jevtrader backtest --csv data/BTCUSDT_1d.csv --report reports/BTC.html

cp .env.example .env                                  # poné tu TYPESAFE_API_KEY
python3 -m jevtrader ping                             # prueba la API de Jev
python3 -m jevtrader backtest --csv data/BTCUSDT_1d.csv --report reports/BTC-jev.html   # ahora con Jev real

python3 -m jevtrader paper --symbol BTCUSDT --once    # procesa la última vela cerrada en papel
python3 -m jevtrader news --asset "Bitcoin (BTC)" --rss https://www.coindesk.com/arc/outboundfeeds/rss/
```

Para correrlo una vez por día en papel, con cron:

```cron
5 0 * * *  cd /ruta/jev-trader && python3 -m jevtrader paper --symbol BTCUSDT --once >> data/cron.log 2>&1
```

## Correrlo en tu PC con Binance (Demo Mode)

Binance bloquea algunas ubicaciones, entre ellas muchos servidores en la nube (error 451). Desde una PC en Argentina funciona.

1. Instalá Python 3.10 o más nuevo y Git. En Windows, marcá "Add Python to PATH" al instalar y usá `py` en vez de `python3`.
2. Bajá el repo y prepará la configuración:
   ```bash
   git clone https://github.com/Nazacarames/APP-ETIQUETAS-JULES.git jev-trader
   cd jev-trader
   cp .env.example .env          # en Windows: copy .env.example .env
   ```
3. Entrá a [demo.binance.com](https://demo.binance.com) con tu cuenta de Binance, abrí **API Key Management** y creá una clave con permiso **solo de trading spot**, sin retiros. Pegá la clave y el secreto en `.env` (`BINANCE_API_KEY`, `BINANCE_API_SECRET`). Si tenés clave de Jev, ponela en `TYPESAFE_API_KEY`; si no, el juez es MockJev.
4. Probá la conexión sin operar, y después la mecánica completa (compra mínima, stop en Binance, venta):
   ```bash
   python3 -m jevtrader binance --check
   python3 -m jevtrader binance --roundtrip-test
   ```
5. Seguí el protocolo de prueba: **[research/PROTOCOLO-DEMO.md](research/PROTOCOLO-DEMO.md)**. Tiene las fases, qué esperar y los umbrales para seguir, frenar o pasar a real, todos decididos antes de empezar. Durante la prueba poné `GATE_SHADOW=true`: la estrategia opera igual y lo que diga Jev queda anotado para medirlo.
6. Procesá la última vela cerrada (compra solo si hay señal y, fuera del modo sombra, Jev la aprueba):
   ```bash
   python3 -m jevtrader binance --symbol BTCUSDT --capital 1000 --once
   ```
   O dejalo corriendo y que revise cada vela sola: `python3 -m jevtrader binance --symbol BTCUSDT --capital 1000`.

Cómo se comporta:
- `--capital` es la plata que el bot puede usar, en USDT. Arriesga 1 % de ese capital por operación y nunca toca otros saldos de tu cuenta.
- Cada compra deja un **stop-loss guardado en Binance**: si tu PC se apaga, el stop sigue activo. Si no puede poner el stop, vende de inmediato.
- Si cancelás el stop a mano, el bot lo vuelve a poner en la próxima vela.
- Estado en `data/binance_demo_state.json` y decisiones en `data/journal.jsonl`.
- Pasar a dinero real requiere dos cambios que hacés vos en `.env`: `BINANCE_ENV=live` y `LIVE_TRADING=true`. Antes, mirá la checklist de más abajo.

## Investigación

- `python3 research/evaluate.py`: backtest de 11 monedas con holdout, grilla de 27 parámetros, costos y velas de 4 h. Resultados en [research/RESULTADOS-2026-10.md](research/RESULTADOS-2026-10.md).
- `python3 research/significance.py`: Sharpe deflactado, probabilidad de sobreajuste (PBO) y Monte Carlo en R.
- **Resumen honesto:** controla muy bien las caídas, pero la ventaja **no es estadísticamente significativa** después de corregir por las combinaciones probadas (Sharpe deflactado 75,5 %, PBO 36 %). Además depende de pocos trades enormes, en especial de 2020.

## Cómo se usa con Claude Code

1. Abrí el proyecto con `claude`. `CLAUDE.md` le da las reglas: Jev juzga y el código ejecuta, no hay lookahead, el holdout no se toca y el dinero real lo activa una persona.
2. Instalá el skill oficial de TypeSafe para que Claude escriba integraciones correctas:
   ```bash
   claude plugin marketplace add typesafe-ai/skills
   claude plugin install typesafe@typesafe-ai
   ```
3. Skills del proyecto:
   - `/backtest`: evaluación disciplinada. Ajusta en el tramo A, valida en el B y compara contra comprar y mantener y contra la estrategia sin Jev.
   - `/jev-question`: agrega una pregunta nueva a Jev con las reglas de diseño de TypeSafe.
   - `/review-journal`: revisión semanal del diario en papel. Propone cambios como diff para que los apruebes.
4. Guardarraíles: `.claude/settings.json` le niega a Claude leer `.env`, y el hook `guard_live.py` bloquea cualquier comando que active `LIVE_TRADING` o apunte a la API real.

Ejemplos de pedidos a Claude Code:
- *"Agregá una pregunta a Jev que detecte si la ruptura ocurre justo antes de un evento macro, y medí si mejora el holdout en BTC, ETH y SOL."*
- *"Probá una estrategia de reversión a la media con la misma interfaz que DonchianTrend y compará."*
- *"Corré /review-journal sobre la última semana."*

## Resultados de ejemplo (velas diarias reales de Binance, juez = MockJev)

> Estos números **no miden a Jev**. MockJev es una heurística local que imita la forma de sus respuestas y sirve para que el pipeline corra sin API key. Con `TYPESAFE_API_KEY` el mismo comando mide a Jev de verdad, por unos US$ 0,001 por activo.

Tramo B (holdout, nunca usado para ajustar). Capital 10.000, 10 bps de comisión + 5 bps de slippage por lado:

| Activo | Variante | Retorno | Máx. DD | Sharpe | Trades |
|---|---|---:|---:|---:|---:|
| BTC (abr-2024 → oct-2026) | Comprar y mantener | +28,3 % | −53,0 % | 0,45 | — |
| | Estrategia base | +3,4 % | −4,4 % | 0,32 | 12 |
| | Base + MockJev | +2,5 % | −1,9 % | 0,54 | 5 |
| ETH (abr-2024 → oct-2026) | Comprar y mantener | −20,9 % | −67,6 % | 0,20 | — |
| | Estrategia base | +2,9 % | −3,2 % | 0,34 | 8 |
| | Base + MockJev | −0,6 % | −1,1 % | −0,22 | 6 |
| SOL (feb-2025 → oct-2026) | Comprar y mantener | −47,3 % | −74,9 % | −0,13 | — |
| | Estrategia base | −0,2 % | −4,2 % | −0,02 | 6 |
| | Base + MockJev | +0,8 % | −1,3 % | 0,36 | 3 |

Cómo leerlo:
- Con 1 % de riesgo por trade, la estrategia arriesga poco y gana poco. Lo que compra es drawdown: −4 % frente a −50/−75 %.
- **El filtro heurístico redujo el drawdown, pero en BTC y ETH vetó señales que habrían rendido más que las tomadas**: +36 % frente a +19 % en BTC y +21 % frente a +14 % en ETH. Esa es exactamente la trampa que el reporte está diseñado para detectar. Con Jev real hay que mirar esa misma métrica antes de confiar en él.
- Con 3 a 12 trades por tramo, todo esto es ruido estadístico. Hace falta más historia, más activos o velas más cortas.

## Pasar de papel a dinero real (checklist)

1. Al menos 3 meses en papel con Jev real y `/review-journal` semanal.
2. Que el holdout muestre una mejora de Jev frente a la base en varios activos, con más de 30 trades.
3. Que las señales vetadas rindan peor que las tomadas.
4. Varias semanas en Binance Demo Mode sin errores de órdenes en el diario. El conector ya deja el stop guardado en Binance.
5. Recién ahí, en tu `.env`: `BINANCE_ENV=live` y `LIVE_TRADING=true`, con un `--capital` que puedas perder entero. Ese paso lo das vos, no el agente.

## Estructura

```
jevtrader/
  config.py      configuración (.env), defaults conservadores
  data.py        velas: Binance público, CSV, sintético
  features.py    indicadores causales -> frases anónimas para Jev
  questions.py   preguntas tipadas (noul/choice/score)
  jev_client.py  cliente /v1/systemone, reintentos, cache, self-consistency, MockJev
  judge.py       política en código sobre las respuestas, fail-closed
  strategy.py    Donchian 20/10 + SMA200 + stop 2xATR
  risk.py        tamaño por riesgo, kill switches
  backtest.py    backtester sin lookahead, métricas, análisis de vetos
  broker.py      PaperBroker, AlpacaBroker (paper por defecto; no probado contra la API real)
  binance.py     Binance Spot: Demo Mode por defecto, stop guardado en el exchange
  live.py        loop en papel (idempotente, una vela por corrida)
  news.py        triage de titulares
  report.py      reporte HTML + JSON
tests/           59 tests (unittest), incluido un exchange Binance simulado
.claude/         settings, hook guard_live.py y 3 skills
```

## Limitaciones conocidas

- `AlpacaBroker` está escrito según la API v2 de Alpaca, pero no se probó contra una cuenta real.
- El conector de Binance está probado contra un exchange simulado (firma, redondeos, stop, cierre). Todavía no se corrió contra Demo Mode porque Binance bloquea el servidor donde se escribió (error 451). La primera prueba real es tu `--check` desde la PC.
- Si el stop de Binance se ejecuta solo en parte, el bot lo ve recién cuando termina de ejecutarse.
- El loop en papel revisa el stop solo en la última vela cerrada. Si se saltea corridas, puede perder un stop intermedio.
- Long-only, un activo por proceso, velas diarias por defecto.
- Jev está en early access: precios, límites y modelos (`jev-latest` = `jev-1.13.0` hoy) pueden cambiar.
