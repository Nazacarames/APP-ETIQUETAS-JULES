# Polylens — guía para Claude Code

Herramienta de análisis en Python (solo librería estándar) sobre datos **públicos** de Polymarket:
quiénes ganan de forma consistente (no solo quién ganó mucho), dónde están apostando hoy, si se los puede
copiar con demora y qué noticias tocan esas apuestas. Jev (TypeSafe AI, "System One") solo lee texto:
clasifica mercados y juzga titulares con preguntas tipadas. Las cuentas las hace el código.

Vos (Claude Code) sos el "System Two": investigás, corrés escaneos, interpretás con cuidado estadístico y
escribís código. Polylens no opera.

## Reglas no negociables
1. **Solo lectura.** Nada de órdenes, billeteras, claves privadas ni clientes de trading (`py-clob-client`,
   endpoints de órdenes de `clob.polymarket.com`). Un hook (`.claude/hooks/guard_secrets.py`) lo bloquea igual.
2. **Argentina.** Polymarket está bloqueado en Argentina desde marzo de 2026 (orden judicial, ENACOM). No ayudes
   a operar desde ahí ni a eludir el bloqueo (VPN, intermediarios, etc.). Analizar datos públicos sí.
3. **No leas `.env`.** Tiene la API key de Jev. Usá `.env.example` como referencia.
4. **Suerte ≠ habilidad.** El ranking de Polymarket muestra quién ganó mucho. Para decir que alguien "es bueno"
   usá el veredicto del escaneo (t con corrección por la cantidad de traders mirados). Si elegís traders
   mirando el ranking y después los testeás con los mismos datos, decilo.
5. **Sin mirar el futuro.** En copiabilidad, el copiador solo usa precios posteriores a la compra del trader +
   demora, y no compra en mercados ya resueltos. Si tocás `study.py`, `tests/test_study.py` tiene que pasar.
6. **Decí con qué juez corriste.** Sin `TYPESAFE_API_KEY` (o con `JEV_MOCK=1`) se usa MockJev, una heurística
   local. Esos resultados no miden a Jev. Decilo siempre.
7. **Nada de aritmética, fechas ni conteos en preguntas a Jev.** Eso va en el código. La opción conservadora o
   neutral va primera ("other", "unclear").
8. **No es una recomendación.** Rendimientos pasados no garantizan nada; no prometas ganancias.
9. **Simulaciones con 100 USD.** Es el presupuesto del usuario: toda simulación arranca con 100 USD y respeta los
   costos (0,1 % por lado en Binance spot) y el mínimo de orden de Binance (5 USDT). Operar con dinero real es
   decisión del usuario y la corre él desde su PC.

## Comandos
```bash
python3 -m unittest discover -s tests -t .              # tests (antes y después de cada cambio, sin red)
python3 -m polylens scan --period month --top 100        # ranking por consistencia → data/scans/
python3 -m polylens trader 0xBILLETERA                   # perfil de una billetera
python3 -m polylens flows                                # posiciones abiertas de los que pasaron el filtro
python3 -m polylens study --top 5                        # ¿se los puede copiar con 1/6/24 h de demora?
python3 -m polylens news --rss <url> [--rss <url>]       # titulares que tocan esas apuestas (Jev)
python3 -m polylens report --out reports/polylens.html   # informe HTML con lo último guardado
python3 -m polylens ping                                 # prueba la API de Jev
```

## Mapa del código
- `polylens/http.py` — GET con caché en disco, ritmo máximo, reintentos y paginación por cursor.
- `polylens/polymarket.py` — Data API v2 y Gamma. Ojo: las posiciones cerradas vienen ordenadas por ganancia;
  `resolved_positions` las pide por fecha y recorta todo a una misma ventana. `prices_history` fecha cada precio
  al final de su balde y descarta el "punto terminal" de la API, que trae el resultado final con fecha anterior.
- `research/polymarket_btc.py` — ¿Polymarket anticipa a BTC en Binance? (no; ver `research/RESULTADOS-polymarket-binance.md`).
- `research/apuestas_futbol.py`, `research/polymarket_deportes.py` — apuestas deportivas con 100 USD (favoritos,
  value betting, surebets, Liga Argentina) y calibración de Polymarket en deportes; ver
  `research/RESULTADOS-apuestas-deportivas.md`. Oddspedia bloquea el acceso automático: no saltear su protección.
- `polylens/profiles.py` — métricas por trader, alertas y ranking con umbrales de azar y Bonferroni.
- `polylens/scan.py` — ranking de Polymarket → perfiles → orden por consistencia.
- `polylens/flows.py` — posiciones abiertas agregadas por mercado (coincidencias y disputas).
- `polylens/study.py` — copiabilidad sobre compras reales (fills agrupados), mantener hasta la resolución.
- `polylens/categories.py`, `polylens/news.py` — preguntas a Jev (categoría; relevancia y dirección).
- `polylens/jev_client.py` — cliente de `/v1/systemone`, caché JSONL, MockJev.
- `polylens/report.py`, `polylens/store.py`, `polylens/__main__.py`.

## Skills del proyecto
- `/polymarket-analysis` — flujo de análisis completo y cómo interpretarlo sin engañarse.
- De estadística (Kryhr, MIT): significancia y métricas deflactadas, sobreajuste, Monte Carlo, lookahead,
  bitácora de investigación. Ver `.claude/skills/THIRD_PARTY.md`.
- Recomendado: skill oficial de TypeSafe (`claude plugin install typesafe@typesafe-ai`).
