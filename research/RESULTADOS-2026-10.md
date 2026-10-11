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
