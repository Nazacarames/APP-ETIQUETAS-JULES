# Protocolo de prueba en Binance Demo Mode

Escrito el 11 de octubre de 2026, **antes** de arrancar la prueba (actualizado el mismo día, también antes de
arrancar, para usar las 11 monedas desde el inicio), siguiendo la skill
`paper-trading-and-forward-test-protocol`. Los umbrales salen de `research/significance.py`. No se cambian
durante la prueba: si cambia una regla del bot, la prueba vuelve a empezar de cero.

## Reglas congeladas

- **Estrategia:** Donchian 20/10, filtro SMA200, stop 2×ATR, velas diarias.
- **Monedas:** las 11 de `research/evaluate.py` (`--symbols top11`). El capital se reparte en 11 bolsas iguales, igual que la cartera del backtest. Cambiar la lista cambia las reglas: el bot no lo permite sobre el mismo archivo de estado.
- **Riesgo:** 1 % de la bolsa de cada moneda por trade (1 R), tope de 50 % por posición, corte por pérdida diaria de 3 %, apagado con caída de 25 %.
- **Juez:** **modo sombra** (`GATE_SHADOW=true`). La estrategia opera siempre y lo que Jev aprobaría o vetaría queda en el diario. Con `TYPESAFE_API_KEY` el juez es Jev real; sin clave es MockJev, y entonces la parte "Jev" de esta prueba no mide nada.
- **Versión del código:** el commit de `main` del día en que arranca la fase 1. Anotalo en `data/journal.jsonl` o en el primer reporte.

## Qué esperar

Esto no es pesimismo, es el perfil normal de esta estrategia.

- Pierde en el 59 % de los trades. El trade mediano es −0,57 R (1 R = el riesgo del trade, 1 % de la bolsa de esa moneda).
- La ganancia viene de pocos trades enormes: los 5 mejores de la historia explican el 47 % del total. Hubo años planos o negativos (2022: −9 R; 2025: −7 R).
- Con 10 trades hay un 28 % de probabilidad de ir perdiendo aunque todo funcione como en el backtest. **No se juzga antes de los 30 trades.**
- **Frecuencia:** BTC solo da unas 4 señales por año; las 11 monedas juntas, unas 40 (≈ 3 por mes). Por eso se usan las 11 desde el día 1, y la fase 1 igual se apoya en pruebas de ida y vuelta.

## Fase 0: preparación (día 1)

1. En `.env`: `BINANCE_ENV=demo`, `LIVE_TRADING=false`, `GATE_SHADOW=true` y las claves de Demo Mode, con permiso solo de trading spot y sin retiros.
2. `python3 -m jevtrader binance --symbols top11 --capital 11000 --check` → conexión OK, permiso de trading "sí" y ninguna moneda con aviso de "capital por moneda chico". En Demo la plata es ficticia: 11.000 USDT dan 1.000 por moneda.
3. `python3 -m jevtrader binance --roundtrip-test` → "OK: compra, stop en Binance, cancelación y venta funcionan."

Si algo de esto falla, no se avanza.

## Fase 1: ejecución (primeras 4 semanas, 11 monedas)

Correr todos los días, 5 minutos después del cierre de la vela diaria, a las 00:05 UTC (21:05 en Argentina):
```
python3 -m jevtrader binance --symbols top11 --capital 11000 --once
```
En Windows: Programador de tareas, acción `py -m jevtrader binance --symbols top11 --capital 11000 --once`, carpeta del repo.
Si dos corridas se pisan, la segunda se niega a arrancar: el estado tiene un candado.

Además, una vez por semana: `python3 -m jevtrader binance --roundtrip-test`.

**Pasa si se cumple todo:**

| Control | Umbral |
|---|---|
| Días con registro en el diario | ≥ 26 de 28 |
| Pruebas de ida y vuelta | 4 de 4 OK |
| `abortada_sin_stop` o posición sin stop | 0 |
| `error_orden` sin explicación | 0 |
| Deslizamiento de entrada vs. cierre de la vela de señal (si hubo entradas) | mediana ≤ 0,30 % |

## Fase 2: ventaja (la misma corrida, hasta llegar a 30 trades)

Sigue la misma corrida de la fase 1, sin reiniciar nada. Con las 11 monedas, llegar a 30 trades cerrados lleva unos 9 meses. Cada salida queda en el diario con su resultado en R (campo `r`). Los umbrales vienen del Monte Carlo por bloques de 5 trades, la versión más pesimista:

| Situación | Umbral | Acción |
|---|---|---|
| Caída acumulada en cualquier momento | > 13,8 R (p95) | Pausar entradas y revisar con `/review-journal` |
| Caída acumulada en cualquier momento | > 17,9 R (p99) | **Falla: se detiene la prueba** |
| Suma de R al llegar a 30 trades | < −6,2 R (p5) | **Falla**: no es consistente con el backtest |
| Suma de R al llegar a 30 trades | ≥ −6,2 R y caída ≤ 13,8 R | **Pasa** |

**Jev en sombra (solo con Jev real):** a los 30 trades se compara el R medio de los trades que Jev habría vetado contra el de los que habría aprobado.

- Jev se activa (`GATE_SHADOW=false`) solo si las dos cosas pasan:
  1. Los vetados rinden menos que los aprobados.
  2. Con el filtro activo, la suma de R habría sido igual o mejor.
- Activarlo cambia las reglas, así que la fase 2 vuelve a empezar.

## Fase 3: dinero real

- **Requisitos:**
  - Las fases 1 y 2 pasaron.
  - Usás un capital que podés perder entero.
  - Mantenés el mismo riesgo de 1 % por trade y los mismos cortes.
- **Cómo se activa:** lo hacés vos, con `BINANCE_ENV=live` y `LIVE_TRADING=true` en tu `.env`. El agente tiene ese paso bloqueado.
- Si decidís pasar a real solo con la fase 1 aprobada, es una decisión de riesgo tuya: el protocolo no la respalda.

## Seguimiento semanal

`/review-journal` compara el diario contra esta tabla: días registrados, errores, R acumulado, caída en R y vetos en sombra. Si se cruza un umbral, la acción es la de la tabla, no una decisión en el momento.
