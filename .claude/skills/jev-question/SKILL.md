---
name: jev-question
description: Diseña, agrega y valida una pregunta nueva para Jev (noul, choice o score) en jevtrader/questions.py siguiendo las reglas de TypeSafe. Usar cuando el usuario quiera que Jev evalúe algo nuevo (p. ej. noticias, régimen, calidad de una salida).
---

# Agregar una pregunta a Jev

Si está instalado, cargá también el skill oficial: `/typesafe:typesafe-ai`
(`claude plugin marketplace add typesafe-ai/skills` y `claude plugin install typesafe@typesafe-ai`).

## Reglas de diseño
- **Atómica**: una propiedad por pregunta. Si hay "y" en la pregunta, probablemente son dos.
- **Semántica, no numérica**: Jev no calcula, no cuenta y lee fechas como texto. Todo número se convierte antes
  en una categoría en `features.py` (y se agrega su frase a `PHRASES`).
- **State mínimo y anónimo**: sin ticker, fecha ni precio cuando la pregunta es sobre comportamiento del precio.
- **Orden conservador**: en `choice`, la opción que lleva a NO operar va primera (Jev tiende a elegir la primera).
- **Inglés** en instrucciones y criterios.
- `choice`: 2–255 opciones. `score`: 2–10 niveles ordenados. `noul`: probabilidad de "sí".
- No preguntes "¿va a subir el precio?": los backtests públicos (egrm07/jev_bitcoin_backtest) no encontraron ventaja.

## Pasos
1. Agregá la pregunta en `jevtrader/questions.py` (en `entry_review` si va en la llamada de entrada: todas las
   preguntas viajan juntas y se responden en paralelo, así que no pueden depender entre sí).
2. Agregá la política en `jevtrader/judge.py`: qué umbral, qué hace (vetar, achicar). Umbrales en `GateConfig`.
3. Dale soporte en `MockJev._answer` para que el pipeline siga corriendo sin API key.
4. Tests en `tests/test_jev_client.py` (veto, tamaño) con `FakeTransport`.
5. Validá con el skill `backtest` y, si hay API key, con `JEV_SAMPLES=3` para ver la estabilidad de la respuesta.
