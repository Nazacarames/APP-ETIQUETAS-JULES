# Polylens

Análisis de los mejores traders y mercados de [Polymarket](https://polymarket.com) a partir de sus **datos públicos**.
Responde cuatro preguntas:

1. **¿Quién gana de forma consistente?** No quién ganó mucho: el ranking oficial está lleno de una o dos apuestas enormes.
2. **¿Dónde están apostando hoy** los que pasaron el filtro? ¿Coinciden o se contradicen?
3. **¿Se los puede copiar?** Qué habría pasado copiando sus compras con 0, 1, 6 o 24 horas de demora.
4. **¿Qué noticias tocan esas apuestas?** [Jev](https://docs.typesafe.ai) (TypeSafe AI) lee titulares y dice si favorecen o perjudican el resultado que tienen.

> ⚠️ **Solo análisis.** Polylens no opera, no firma órdenes y no usa billeteras. Polymarket está **bloqueado en Argentina** desde marzo de 2026 (orden judicial; ENACOM ordenó el bloqueo). Esta herramienta no sirve para eludirlo. Nada de esto es una recomendación de inversión: rendimientos pasados no garantizan nada.

## Uso rápido

Necesita Python 3.10 o más nuevo. No usa dependencias externas.

```bash
python3 -m polylens scan --period month --top 100     # unos minutos la primera vez; después usa la caché
python3 -m polylens flows                             # posiciones abiertas de los que pasaron el filtro
python3 -m polylens study --top 5                     # copiabilidad con demora
python3 -m polylens news --rss https://feeds.bbci.co.uk/news/world/rss.xml
python3 -m polylens report --out reports/polylens.html
python3 -m polylens trader 0xBILLETERA                # perfil de una billetera puntual
```

Los resultados se guardan en `data/scans/`, `data/flows/`, `data/studies/` y `data/news/`: uno con fecha por corrida y un `latest.json`. Comparar escaneos de distintas semanas es la mejor prueba de si una racha era habilidad o suerte.

Jev es opcional. Copiá `.env.example` a `.env` y poné tu `TYPESAFE_API_KEY`. Sin clave, las categorías se asignan por palabras clave y las noticias se cruzan por palabras en común. En ese caso la dirección queda siempre en "no está claro". El programa avisa cuál de los dos jueces usó.

## Cómo funciona

### 1. Escaneo: consistencia, no tamaño
- Toma el top N del [ranking de Polymarket](https://data-api.polymarket.com/v2/openapi.json) para un período y una categoría.
- Para cada trader lee sus **posiciones con resultado** de los últimos 90 días: cerradas, ganadas sin cobrar y perdidas que dejó vencer. Si faltaran las perdidas, quien nunca cierra lo que pierde parecería infalible.
- **Trampa de la API:** por defecto las posiciones cerradas vienen ordenadas por ganancia. Si se corta la lista, quedan solo las ganadoras. Polylens las pide ordenadas por fecha y recorta todos los tipos a una misma ventana. Sin este arreglo, la mitad del top aparecía con 100 % de aciertos.
- Métricas: aciertos, ROI, peor pérdida, cuánto explica la mejor apuesta y si sigue ganando en la mitad más reciente. También mide qué parte del dinero puso en "casi seguros" (≥ 0,90) y en batacazos (≤ 0,20), y cuántas operaciones hace por día (más de 300 sugiere un bot).
- **Consistencia** = estadístico t de los retornos por posición (recortados a −100 %…+1000 %).
- **Corrección por mirar a muchos**: entre N traders, alguno parece bueno por azar. "Prometedor" supera el mejor t esperable por suerte, Φ⁻¹(1 − 1/N). "Sólido" supera Bonferroni al 5 %, Φ⁻¹(1 − 0,05/N).
- Alertas: pocas posiciones, una sola apuesta que explica todo, probable bot, "ganaba y ahora pierde". También marca apuestas grandes a precio bajo, a menos de 48 h del cierre, que salieron bien: es un patrón de información anticipada (o de mucha suerte) para mirar de cerca.

### 2. Flujos
Junta las posiciones abiertas de los traders "sólidos" y "prometedores" por mercado y resultado. Muestra cuántos coinciden, cuánto dinero hay y a qué precio entraron. También cuánto paga cada dólar si ese resultado gana, y si otro de ellos apuesta al resultado contrario ("en disputa").

### 3. Copiabilidad
Usa las **compras reales** del trader, incluidas sus órdenes límite. Los fills del mismo token dentro de una hora cuentan como una sola entrada. El estudio se hace sobre una muestra de mercados ya resueltos:
- **Trader (mantener):** su precio de compra → 1 si ganó, 0 si perdió.
- **Copiador:** compra lo mismo con 0, 1, 6 y 24 h de demora al precio de ese momento, más 1 centavo de deslizamiento, y mantiene hasta la resolución. Si el mercado ya se resolvió, esa compra no se puede copiar.
- Da el promedio, la mediana, el porcentaje de aciertos, un intervalo de confianza del 95 % por bootstrap y cuánto se movió el precio después de su compra.

### 4. Noticias con Jev
Un filtro barato arma pares titular–mercado con al menos dos palabras significativas en común. Después Jev responde dos preguntas tipadas por par:
- `noul`: ¿el titular afecta directamente la probabilidad de ese resultado?
- `choice`: ¿lo empuja **a favor** o **en contra** del resultado que tienen los traders seguidos? La primera opción es "no está claro", porque Jev tiende a elegir la primera cuando duda.

Jev también puede clasificar cada evento por categoría (política, deportes, cripto, economía, geopolítica, cultura, tecnología) con `scan --jev`. El tope por defecto es de 300 preguntas: Jev ve primero los eventos con más dinero y el resto se clasifica por palabras clave. Siguiendo la guía de TypeSafe, a Jev nunca se le pide aritmética, fechas ni conteos: eso lo hace el código.

## Qué mostró una primera corrida (11/10/2026)

Top 40 del ranking mensual, posiciones de los últimos 90 días. Las categorías salieron de palabras clave (MockJev), no de Jev.

| Veredicto | Traders |
|---|---|
| sólido | 3 |
| prometedor | 1 |
| no se distingue de la suerte | 16 |
| negativo (perdió en sus posiciones con resultado) | 13 |
| muestra chica (< 20 posiciones) | 7 |

- **Estar arriba en el ranking del mes no dice casi nada.** De los 33 con muestra suficiente, 11 perdieron plata en total en sus posiciones de los últimos 90 días, aunque el ranking del mes los muestre ganando. El caso extremo figura con +338 mil USD en el mes y acumula −2,8 millones en 90 días.
- "Negativo" significa que su posición típica pierde. Algunos de esos 13 igual terminan en verde porque aciertan pocas apuestas grandes (ROI +4,7 % con t −0,98): es un perfil frágil.
- **Copiabilidad** (4 mejores, hasta 60 compras cada uno, últimos 30 días, mercados resueltos):
  - El "sólido" con mejor t gana con su operatoria (entrar y salir), no manteniendo. Sus compras mantenidas hasta el final rendían −19 %, y copiadas con 1 h de demora, −20 %.
  - En el agregado de los cuatro, copiar con 1 h de demora dio −8,9 % por compra (IC 95 %: −21,2 %…+5,4 %). Con 24 h, −15,3 %.
  - Ninguno resultó "copiable" con la muestra disponible.
- Jev (jev-1.13.0) juzgó titulares de Ormuz e Irán contra los mercados abiertos de esos traders con criterio razonable. Ejemplo: "se intensifican los ataques en Ormuz" → a favor del "No" en "¿acuerdo EE. UU.–Irán por Ormuz antes del 31/10?", con confianza 0,95.

Son datos de un solo día y de pocos traders: sirven para ver cómo leer el informe, no como conclusión.

## Polymarket y Binance
`research/polymarket_btc.py` prueba si las probabilidades diarias de Polymarket sobre Bitcoin anticipan el precio
en Binance, simulando con 100 USD. No lo anticipan: esos mercados se resuelven con el precio de Binance y lo siguen.
Detalle y simulaciones de la estrategia anterior con 100 USD en `research/RESULTADOS-polymarket-binance.md`.

## Apuestas deportivas
`research/apuestas_futbol.py` (cuotas históricas de football-data.co.uk) y `research/polymarket_deportes.py`
(calibración de Polymarket en deportes) responden si hay apuestas de alta tasa de acierto que dejen ganancia,
simulando con 100 USD. Resumen en `research/RESULTADOS-apuestas-deportivas.md`: acertar seguido es fácil, ganar plata
no; la única ventaja aparece buscando la mejor cuota entre decenas de casas.

## Analista de fútbol argentino (`python3 -m futbol`)
Analiza la Liga Profesional Argentina con datos de [API-Football](https://www.api-football.com) para apuestas
en bet365 desde Provincia de Buenos Aires, donde el usuario confirmó con bet365 que puede acceder y apostar.
Solo analiza y anota en papel: las apuestas las decide y las hace el usuario desde su cuenta; el programa no entra
a bet365 (sus reglas prohíben el acceso automático) y toma las cuotas de API-Football o de la carga manual.

- **Remates por jugador.** Para cada titular calcula la probabilidad de 1, 2 o 3 remates (totales y al arco).
  Usa su ritmo por 90 minutos contraído hacia el promedio de su posición, los minutos que juega de titular, cuánto
  concede el rival y la localía, con una binomial negativa. bet365 liquida estos mercados con datos de Opta; API-Football
  no es Opta, así que puede haber diferencias de conteo.
- **Validación sin mirar el futuro.** `validar` predice cada partido solo con los anteriores y compara contra la
  línea base "a ojo" (en cuántos partidos de titular llegó a ese número).
- **Valor.** `partido <id>` compara con las cuotas de bet365 que traiga la API (casa ID 8) y con las que cargues a mano
  en `data/futbol/cuotas.csv`. Sugiere monto con 100 USD (un cuarto de Kelly, tope 3 %) y con `--anotar` lo
  deja en el diario en papel. `papel` lo liquida con lo que pasó.
- **Minutos.** `minutos` dice qué tan probable es otro gol desde cada minuto según el resultado, y si una cuota en
  vivo paga bien.
- **Cuotas de hoy** (`cuotas --fecha AAAA-MM-DD` o `--partido ID`). El plan gratis no da la temporada 2026 por liga,
  pero sí las cuotas de cada partido, de bet365 y de otras 8 casas, con los planteles actuales. Compara bet365 contra
  Pinnacle sin margen en ganador, goles y ambos marcan. También marca incoherencias de bet365 en mercados de jugadores:
  si un gol paga menos que un remate al arco, o 2+ remates menos que 1+, uno de los precios está mal. Muestra la
  probabilidad implícita de cada jugador y con `--anotar` deja las de valor en papel. `papel --resultado ID:2-1`
  las liquida.
- **Jev** lee titulares y avisa si un jugador no juega o está en duda; la formación oficial manda.
- **Cupo gratis:** 100 pedidos por día y solo temporadas 2022–2024. Un partido = 1 pedido; `sync` sigue donde quedó.
  Para la temporada actual (2026) hace falta un plan pago.

```bash
python3 -m futbol sync                 # repetir cada día hasta completar 2024 (~6 días con el plan gratis)
python3 -m futbol validar
python3 -m futbol remates --top 20
```

## Limitaciones
- El costo de cada posición sale del precio promedio que informa la API. En mercados de "riesgo negativo" (conversiones entre resultados) puede no coincidir con lo que el trader pagó realmente, así que el ROI es aproximado.
- La copiabilidad usa solo mercados ya resueltos dentro de la ventana. Eso favorece mercados cortos (deportes, cripto diario).
- Los traders muy activos llegan rápido al tope de 3000 fills, así que su ventana efectiva es más corta y se informa.
- El historial de precios tiene la resolución que elige la API (1 min a 12 h según la antigüedad). Cada precio se fecha al final de su balde y se descarta el punto final que la API agrega con el resultado: así no se filtra el futuro. Un precio "a la hora t" es el primero conocido hasta 2 h después.

## Estructura

```
polylens/
  http.py         GET con caché en disco, ritmo máximo, reintentos y paginación por cursor
  polymarket.py   Data API v2 + Gamma (ranking, posiciones, operaciones, precios, mercados)
  profiles.py     métricas por trader, alertas y ranking con corrección estadística
  scan.py         ranking → perfiles → orden por consistencia
  flows.py        posiciones abiertas agregadas por mercado
  study.py        copiabilidad con demora sobre compras reales
  categories.py   categoría de cada evento (Jev o palabras clave)
  news.py         titulares ↔ mercados con Jev
  jev_client.py   cliente de Jev (/v1/systemone), caché y MockJev
  report.py       informe HTML autocontenido
  store.py        resultados guardados con fecha
futbol/
  api.py          cliente de API-Football (clave en encabezado, sin cachear errores)
  datos.py        descarga incremental y tabla de apariciones por jugador
  modelo.py       remates por jugador y validación sin lookahead
  valor.py        cuotas de bet365, valor, monto y diario en papel
  minutos.py      probabilidad de otro gol por minuto y resultado
  noticias.py     Jev: jugadores en duda o descartados
  cuotas.py       bet365 contra Pinnacle e incoherencias de bet365 (cuotas actuales)
tests/            sin red: transportes falsos y datos sintéticos
.claude/          hook que bloquea leer .env y operar; skill /polymarket-analysis; skills de estadística
```

```bash
python3 -m unittest discover -s tests -t .
```

## Claude Code
`CLAUDE.md` tiene las reglas del proyecto. La skill `/polymarket-analysis` guía un análisis completo y explica cómo interpretarlo sin confundir suerte con habilidad. El hook `.claude/hooks/guard_secrets.py` bloquea leer `.env` y cualquier intento de operar.
