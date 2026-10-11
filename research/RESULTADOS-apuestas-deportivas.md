# Apuestas deportivas con alta tasa de acierto: simulaciones con 100 USD (11 de octubre de 2026)

Pregunta: ¿hay apuestas que se ganen casi siempre **y** que dejen plata? Todo se simula con 100 USD y una apuesta
fija de 2 USD (2 %). Son datos históricos: no se apostó nada.

- `python3 research/apuestas_futbol.py`: 53.486 partidos de 11 ligas europeas (2012/13 → 2026/27) y 6.399 de la
  Liga Profesional Argentina. Las cuotas son de football-data.co.uk, tomadas antes del partido.
- `python3 research/polymarket_deportes.py`: 5.057 resultados de Polymarket (fútbol, NBA, NFL, MLB y tenis, de
  diciembre de 2025 a octubre de 2026), con el precio que se conocía 1 hora antes del partido.

Tramo A = 2012/13–2021/22. Tramo B = 2022/23 en adelante. Lo que vale es lo que se repite en los dos.

## 1. Acertar seguido es fácil; ganar plata, no

| Favorito con cuota… | Aciertos | ROI en una casa promedio (A / B) | Con 100 USD en B |
|---|---:|---:|---:|
| 1,01–1,25 | 84,5 % | −1,3 % / −0,8 % | 84,50 |
| 1,25–1,40 | 75–77 % | −0,5 % / +2,2 % | 154,80 |
| 1,40–1,60 | 64–65 % | −3,0 % / −4,3 % | se queda sin plata |
| 1,60–1,90 | 56–57 % | −2,3 % / −1,1 % | se queda sin plata |

- **La tasa de acierto alta ya está en la cuota.** A 1,20 se gana 5 de cada 6 veces, pero se cobra poco. La sexta
  vez que se pierde se lleva lo ganado en las otras cinco, y el margen de la casa termina inclinando la cuenta.
- El +2,2 % del tramo B en 1,25–1,40 no se repite en el tramo A (−0,5 %), y su intervalo incluye 0: no es una
  ventaja confirmada.

## 2. La única ventaja que aparece necesita la mejor cuota de decenas de casas

- Con la **mejor cuota del mercado** (la más alta entre decenas de casas), el favorito a 1,25–1,40 dio +2,9 % (A)
  y +4,8 % (B), con intervalos por encima de 0. Es el sesgo favorito–batacazo: las casas cobran más margen en los
  batacazos que en los favoritos.
- Pero una persona no tiene cuenta en decenas de casas. Comparando entre **1 a 4 casas grandes**, la misma
  apuesta da entre −0,6 % y +0,4 %: nada.
- En Argentina hay pocas casas con licencia por provincia, así que el escenario realista es el de 1 a 4 casas.

## 3. Value betting y surebets

- **Value betting** (apostar cuando una casa paga más que la probabilidad justa de Pinnacle): en el tramo A daba
  +2 %, pero en el B dio **−7,9 %**. Con Bet365 los resultados son ruido (intervalos de ±20 %).
- **Surebets** (cubrir los tres resultados con ganancia asegurada): entre 4 casas grandes aparecen en el 1,2 % de
  los partidos y dejan una mediana de 0,31 %, unos **31 centavos con 100 USD**. Además, las casas cierran o
  limitan las cuentas que hacen esto.

## 4. Liga Profesional Argentina

- El 30 % de los partidos termina empatado: hasta los favoritos fuertes (cuota ≤ 1,50) ganan solo el 69 %.
- Apostando al favorito con la cuota promedio de cierre, el ROI da entre −2,5 % y −6,1 %. Ningún rango deja
  ganancia confirmada.

## 5. Polymarket como referencia

Las probabilidades de Polymarket 1 hora antes de los partidos están bien calibradas: lo que cotiza a 0,30 gana el
29,6 %, a 0,64 el 64,2 % y a 0,74 el 76,6 %. Todas las diferencias están dentro del margen de error. Sirve como
"probabilidad justa" para comparar con la cuota de una casa: si la casa paga más que 1 / probabilidad (más un
margen), es una apuesta de valor. Pero no tiene sesgos que se puedan explotar por sí mismo. Polymarket está
bloqueado en Argentina: esto solo usa sus datos públicos.

## Oddspedia

`oddspedia.com` bloquea el acceso automático con una verificación de Cloudflare (responde 403), y no corresponde
saltearla. Para analizar sus cuotas hay dos caminos: copiarlas a mano (o con capturas) para que el código calcule
probabilidad justa, valor y surebets, o usar una API de cuotas con licencia (algunas tienen plan gratuito).

## Conclusión

No hay una apuesta deportiva de "alta tasa de éxito" que deje ganancia confirmada para alguien con pocas casas.
Lo que más se acerca es apostar a favoritos fuertes (1,25–1,40) buscando siempre la mejor cuota entre muchas
casas: +3 % a +5 % por apuesta. Son unas 290 apuestas de 2 USD por temporada en las 11 ligas (6 por semana), y
dejaron **entre 16 y 29 USD por temporada con 100 USD** (tramos A y B). Eso requiere cuentas en muchas casas y que
no limiten la cuenta. Con 1 a 4 casas, el resultado esperado es perder de a poco.
