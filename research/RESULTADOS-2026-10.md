# Evaluación antes de operar — 11 de octubre de 2026

Reproducir: `python3 research/evaluate.py` (baja los datos que falten de Binance).

- **Datos:** velas diarias de Binance desde 2018 (o desde que cotiza cada moneda). Además, velas de 4 h de BTC y ETH.
- **Supuestos:** 10 bps de comisión + 5 bps de slippage por lado. Riesgo de 1 % por trade. Parámetros Donchian 20/10, stop 2×ATR, sin cambios.
- **Juez:** **MockJev** (heurística local). **Ningún número de este archivo mide a Jev real**: no había API key.
- **Tramos:** A = primer 70 % de cada serie (desarrollo). B = último 30 % (holdout; empieza entre abril de 2024 y febrero de 2025, según la moneda).
- **Activos "vistos"** (BTC, ETH, SOL): su tramo B ya se había mirado al desarrollar el bot.
- **Activos "nuevos"** (BNB, XRP, ADA, DOGE, LTC, LINK, AVAX, TRX): nunca se habían mirado, así que su tramo B es la prueba fuera de muestra.

## Resumen (medianas por grupo)

| Grupo | Tramo | Variante | Retorno | Máx. caída | Sharpe |
|---|---|---|---:|---:|---:|
| Nuevos (8) | B | Comprar y mantener | +0,6 % | −73,7 % | 0,36 |
| Nuevos (8) | B | Estrategia base | +3,5 % | −7,5 % | 0,28 |
| Nuevos (8) | B | Base + MockJev | +0,1 % | −1,6 % | 0,04 |
| Vistos (3) | B | Comprar y mantener | −20,9 % | −67,6 % | 0,20 |
| Vistos (3) | B | Estrategia base | +2,9 % | −4,2 % | 0,32 |
| Todos (11) | A | Estrategia base | — | — | 0,80 |

**Cartera equiponderada de las 11 monedas** (abril de 2021 → octubre de 2026):

| Variante | Retorno | CAGR | Máx. caída | Sharpe |
|---|---:|---:|---:|---:|
| Comprar y mantener | +10,4 % | +1,8 % | −84,3 % | 0,39 |
| Estrategia base | +14,0 % | +2,4 % | −4,8 % | 0,66 |

**Retorno medio por trade** (bootstrap, IC 95 %):

| Tramo | Trades | Media | IC 95 % | Ganadores |
|---|---:|---:|---|---:|
| A (11 activos) | 213 | +19,7 % | [+10,2 %, +30,2 %] | 43 % |
| B, nuevos | 58 | +6,7 % | [−3,2 %, +21,8 %] | 34 % |
| B, vistos | 26 | +1,5 % | [−2,9 %, +6,9 %] | 46 % |

## Conclusiones

1. **La estrategia base controla el riesgo, pero su ventaja fuera de muestra no está probada.**
   - En el holdout de los activos nuevos, el retorno medio por trade es positivo, pero el intervalo incluye el cero.
   - Su Sharpe (0,28) es parecido al de comprar y mantener (0,36), con una caída diez veces menor (−7,5 % contra −73,7 %).
2. **Los parámetros no están sobreajustados.** En el tramo A, las 27 combinaciones dan Sharpe medianos de 0,58 a 0,80. Los actuales (20/10/2) quedan arriba, pero dentro de una meseta. No se cambiaron, así que el tramo B sigue siendo válido para estos parámetros.
3. **Los costos casi no pesan.** Hay pocos trades: con costos cuatro veces mayores, el Sharpe mediano baja de 0,63 a 0,59.
4. **Las velas de 4 h no ayudan.** Rinden muy bien en A (Sharpe de 1,4 a 1,8) pero se caen en B (BTC −3,6 %), señal de que el contexto cambió.
5. **MockJev como filtro no sirve.** Las señales que vetó (535) rindieron en promedio +16,5 %, y las que dejó pasar (178), +16,1 %. Filtra al azar y además achica el retorno. Falta medir **Jev real** con la misma prueba: cuesta menos de US$ 0,05 para las 11 monedas.
6. **Los retornos absolutos son chicos a propósito.** Con 1 % de riesgo por trade y la plata repartida en 11 monedas, el bot arriesga muy poco. Subir el riesgo sube el retorno y la caída casi en la misma proporción.

## Sesgos a tener en cuenta

- **Supervivencia:** las 11 monedas son grandes hoy. Las que desaparecieron no están, y eso infla los resultados del tramo A, sobre todo los de comprar y mantener.
- **Holdout ya usado:** desde este informe, el tramo B de las 11 monedas ya se miró. Cualquier cambio futuro se valida con datos posteriores al 10 de octubre de 2026: Demo Mode o papel hacia adelante.

## Próximos pasos

1. Conseguir la API key de Jev y repetir esta evaluación con Jev real. Hay que mirar sobre todo si las señales vetadas rinden menos que las tomadas.
2. Correr Binance Demo Mode varias semanas. Es el único holdout limpio que queda.
3. Si se quiere operar varias monedas, primero hay que sumar soporte multi-símbolo al loop de Binance. Hoy el estado se guarda en un único archivo: no corras varios procesos a la vez.
4. Dinero real recién con un resultado positivo en el punto 1 o en el 2, y con un capital que se pueda perder.

## Anexo: significancia y Monte Carlo (`research/significance.py`)

Cartera equiponderada de las 11 monedas, rebalanceo diario, 1.998 días (abril de 2021 → octubre de 2026), parámetros 20/10/2.

| Medida | Valor | Lectura |
|---|---:|---|
| Sharpe anual | 0,70 | Puesto 11 de las 27 combinaciones de la grilla |
| P(Sharpe real > 0), sin corregir | 94,4 % | Casi significativo |
| Sharpe que daría el azar con 27 pruebas | 0,39 | Umbral del Sharpe deflactado |
| **Sharpe deflactado: P(real > azar)** | **75,5 %** | **No significativo** (haría falta ≥ 95 %) |
| **PBO** (CSCV, 16 bloques, 12.870 particiones) | **35,9 %** | Menos de 50 %: hay algo de sobreajuste, pero no domina |
| P(Sharpe del "ganador" < 0 fuera de muestra) | 4,6 % | El mejor de cada partición rara vez pierde afuera |
| Asimetría / curtosis diaria | −1,19 / 29,1 | Colas gordas: pocos días explican mucho |

**Trades (297 de las 11 monedas, en R):**

- **Distribución:** media +1,58 R, mediana −0,57 R, 41 % ganadores. El peor trade fue −1,07 R y el mejor, +63,9 R.
- **Dependencia de pocos trades:** los 5 mejores trades son el 47 % del total y los 10 mejores, el 67 %. Sin los 10 mejores, la media cae a +0,54 R. El tramo B tiene una media de +0,80 R, pero sin el mejor trade (XRP, +41,7 R) baja a +0,31 R.
- **Por año:** 2019 +22 R · 2020 +247 R · 2021 +68 R · 2022 −9 R · 2023 +63 R · 2024 +74 R · 2025 −7 R · 2026 +10 R.
- **Rachas:** la caída histórica, con los trades en su orden real, fue de 32,3 R. Es peor que el p95 del Monte Carlo por bloques (26,9 R): las pérdidas se agrupan en el tiempo porque las monedas se mueven juntas. Hay que planificar el riesgo con la caída histórica, no con la mediana.

**Conclusión:** la estrategia tiene un perfil de tendencia real (pocas ganancias grandes, muchas pérdidas chicas), pero la evidencia **no alcanza para afirmar una ventaja** después de corregir por las 27 pruebas, y depende mucho de 2020. Los umbrales del Monte Carlo están en `research/PROTOCOLO-DEMO.md`.
