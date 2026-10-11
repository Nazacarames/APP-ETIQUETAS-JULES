# ¿Analizar Polymarket y operar en Binance? Simulaciones con 100 USD (11 de octubre de 2026)

Pregunta: ¿sirve lo que se ve en Polymarket para operar Bitcoin en Binance? Todas las simulaciones usan
**100 USD** de capital inicial. En Binance spot se cobra 0,10 % de comisión por lado; además se suma 0,05 % de
deslizamiento. Son simulaciones con datos históricos: no se operó nada.

## 1. Las probabilidades de Polymarket sobre Bitcoin no anticipan el precio

`python3 research/polymarket_btc.py --capital 100`

- **Datos:** 415 mercados diarios "Bitcoin Up or Down" (2 de agosto de 2025 → 11 de octubre de 2026). Cada uno
  pregunta si BTC/USDT **en Binance** va a cerrar más arriba a las 12:00 de Nueva York que el día anterior.
- **Señal:** la probabilidad de "Up" que ya se conocía al empezar cada ventana de 24 h.
- **Resultado:** casi siempre está en 0,50 ± 0,01 (rango 0,44–0,56). No predice nada: la correlación con el
  retorno de BTC es −0,06 (p = 0,23) y el Brier, 0,2508, es apenas peor que decir siempre 50 % (0,2500).
- **Por qué:** estos mercados se resuelven con el precio de Binance y los arbitrajistas los ajustan a ese precio.
  Polymarket sigue a Binance, no al revés.

| Regla con 100 USD | Total | Operaciones |
|---|---:|---:|
| Comprar y mantener BTC | 74,14 USD | 1 |
| Comprar y vender todos los días | 18,96 USD | 415 |
| Seguir al público (p(Up) > 0,50) | 32,10 USD | 253 |
| Ir contra el público (p(Up) < 0,50) | 90,32 USD | 112 |
| Seguir al público (p(Up) > 0,52) | 85,81 USD | 37 |
| Ir contra el público (p(Up) < 0,48) | 103,43 USD | 10 |

Operar todos los días se come el capital en comisiones: 415 idas y vueltas al 0,3 % cuestan más del 70 %.
El +3,43 USD de la última fila sale de 10 operaciones elegidas entre 4 reglas probadas: es ruido.

**Corrección de datos encontrada en el camino.** El historial de precios de Polymarket fecha cada punto al
*inicio* de su balde (de 1 min a 12 h, según la antigüedad). Además, agrega un punto final con el resultado del
mercado, fechado *antes* de la resolución. Con los datos crudos, la regla "seguir al público" pasaba de 100 a
678 USD: era el resultado filtrándose hacia atrás. `Polymarket.prices_history` ahora descarta ese punto y fecha
cada precio al final de su balde. El estudio de copiabilidad de Polylens casi no cambió: usa datos recientes
con baldes de 5 minutos y ya descartaba precios de 0 o 1.

## 2. La estrategia anterior para Binance, con 100 USD

Donchian 20/10 + filtro SMA200 + stop 2×ATR, con 1 % de riesgo por operación (1 USD con 100 USD). El código
está en el historial de git (commit `1e55112`, `jevtrader/`). Estos números agregan el mínimo de orden de
Binance (5 USDT) a la evaluación de `RESULTADOS-2026-10.md` de ese commit. No se ajustó ningún parámetro.

| Cartera (100 USD) | Desde | Final | Peor caída | Operaciones | Rechazadas por mínimo | Comprar y mantener |
|---|---|---:|---:|---:|---:|---:|
| Solo BTC | 1/4/2021 | 114,94 | −6,4 % | 22 | 0 | 140,26 |
| Solo BTC | 10/10/2024 | 106,32 | −4,4 % | 8 | 0 | 135,87 |
| Solo BTC | 10/10/2025 | 100,84 | −2,8 % | 2 | 0 | 67,72 |
| BTC + ETH | 1/4/2021 | 110,73 | −5,5 % | 37 | 33 | 134,74 |
| BTC + ETH + SOL | 1/4/2021 | 108,22 | −3,6 % | 22 | 178 | 276,95 |
| 11 monedas | 1/4/2021 | 100,00 | 0 % | **0** | 853 | 179,13 |

- **Con 100 USD, una sola moneda.** Repartidos en 11 monedas quedan 9,09 USD por moneda, y el tope del 50 % por
  posición da órdenes de 4,55 USD. Binance las rechaza todas. Con 3 monedas se rechaza la mayoría.
- **Gana poco y pierde poco.** Solo BTC: +14,94 USD en cinco años y medio (≈ +2,5 % anual, unos 25 centavos por
  mes), con una caída máxima de 6,4 USD. En el último año BTC cayó 32 % y la estrategia quedó en +0,84 USD,
  porque el filtro la dejó afuera de la caída.
- **La ventaja no está probada.** El Sharpe deflactado es 75,5 % (haría falta ≥ 95 %), y el resultado depende
  mucho de 2020 y de pocos trades grandes.

## Conclusión

1. **Analizar Polymarket y operar en Binance se puede técnicamente.** Polylens lee datos públicos de Polymarket
   y Binance funciona en Argentina; el bloqueo de Polymarket no cambia nada de esto. Pero **hoy no hay nada que
   conectar**: la señal más directa de Polymarket sobre BTC no anticipa a Binance.
2. **Lo que falta probar** (con la misma disciplina, antes de arriesgar plata):
   - Mercados de eventos macro (decisiones de la Fed, regulación, ETF) como filtro de riesgo: salir de BTC cuando
     sube la probabilidad de un evento negativo.
   - Posiciones de los traders "sólidos" de Polylens en mercados cripto.
3. **Con 100 USD:** si se opera, conviene una sola moneda (BTC), primero en Demo Mode, con expectativas del orden
   de centavos por mes. Pasar a dinero real es una decisión del usuario, con plata que pueda perder.
