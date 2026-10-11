# Cómo trabajan las apps de análisis de apuestas (y qué tomamos para el analista)

Relevamiento del 11 de octubre de 2026. La mayoría de las fuentes son de los propios vendedores: sus cifras de
rendimiento no están verificadas.

## 1. De dónde sacan las cuotas ("dónde ven las bets")

Ninguna app seria lee las páginas de las casas a mano. Compran **feeds de cuotas** que juntan decenas de casas
(APIs comerciales como las de OddsJam, SportsGameOdds, OddsPapi u odds-api.io). Además usan una **casa "aguda" como
referencia**: Pinnacle, o una bolsa de apuestas como Betfair.

**Nosotros:** API-Football trae, por partido, bet365 y otras 8 casas, Pinnacle y Betfair incluidas. Funciona en el
plan gratis para la temporada actual. Es la misma idea, a escala chica.

## 2. Valor esperado contra una referencia sin margen (OddsJam, Outlier, RebelBetting)

- Se le quita el margen a Pinnacle, o al promedio del mercado, para obtener la "cuota justa". Después se buscan
  casas blandas que paguen más: valor = probabilidad justa × cuota − 1
  ([RotoWire sobre OddsJam](https://www.rotowire.com/news/best-betting-strategy-for-the-long-term-get-a-7-day-free-trial-for-sharp-money-97444),
  [SharpAPI](https://sharpapi.io/use-cases/ev-betting-tool),
  [SportsGameOdds](https://sportsgameodds.com/use-cases/positive-ev-betting-api)).
- Las oportunidades duran segundos o minutos. Un valor mayor a ~20 % suele ser un error de datos, no un regalo
  ([dev.to](https://dev.to/drengregious/oddsjam-alternative-a-better-approach-to-finding-ev-betting-opportunities-1i8n)).
- RebelBetting cobra unos 129 € por mes. Su fundador reconoce que las casas grandes **limitan los montos** de quien
  gana ([FT vía euro2day](https://www.euro2day.gr/ftcom_en/article-ft-en/1248302/gambling-software-rebelbetting-enables-punters-to.html)).
  Una tesis de Padua con datos de RebelBetting subraya la importancia de manejar el capital
  ([unipd](https://thesis.unipd.it/handle/20.500.12608/52431)).

**Nosotros:** `futbol cuotas` compara bet365 contra Pinnacle sin margen y descarta grupos de cuotas que no cierran.

## 3. Valor de cierre (CLV): cómo saben si funciona sin esperar meses

Comparan la cuota que tomaste con la del cierre, justo antes del partido. Si le ganás al cierre de forma sostenida,
la ventaja es real aunque los resultados todavía no la muestren. Los propios vendedores lo llaman "el mejor
indicador temprano" ([SharpAPI](https://sharpapi.io/use-cases/ev-betting-tool)).

**Nosotros:** `futbol papel --clv` agrega a cada apuesta en papel su valor de cierre. En mercados del partido se
compara contra Pinnacle sin margen; en jugadores, contra el cierre de bet365.

## 4. Movimientos de cuotas ("dropping odds", steam)

Pinnacle se mueve primero cuando entra plata informada, y las casas blandas tardan en acompañar. La señal es esa
demora: una casa blanda que todavía paga el precio viejo
([odds-api.io](https://docs.odds-api.io/guides/dropping-odds),
[OddsPapi](https://oddspapi.io/blog/?p=2886),
[SharpAPI](https://sharpapi.io/learn/line-movement-sports-betting)). No todo movimiento es plata informada: también
hay ruido y noticias, y conviene ver que el nuevo precio se sostenga.

**Nosotros:** cada vez que se corre `futbol cuotas`, se guarda una foto de las cuotas en `data/futbol/snapshots/`. Si
Pinnacle bajó una cuota y bet365 no la acompañó, avisa "bet365 atrasado". API-Football actualiza las cuotas cada
algunas horas, no en tiempo real.

## 5. Mercados de jugadores: tasa de acierto de los últimos partidos (Fobal, Statz, playerstats)

Muestran cuántas veces un jugador superó la línea en sus últimos 5 o 10 partidos, y filtran, por ejemplo, "1+
remate al arco con 80 % de acierto en los últimos 5"
([Fobal](https://mwm.ai/apps/fobal-predictions-picks/6761837044),
[Statz](https://statz.ai/news/saturday-bet-builder-tips-shots-on-target-21-march-2026),
[StatsHub](https://statshub.com/es/betting-academy/how-to-bet-on-football-player-shots-complete-guide),
[playerstats.football](https://playerstats.football/championship/hull-city/shots-on-target)).
Es lo que la gente llama "alta tasa de éxito".

**Cuidado:** 4 de 5 es una muestra mínima, y la casa ya ve esos mismos números al poner la cuota. La tasa de acierto
solo sirve si se la compara con la probabilidad que implica la cuota.

**Nosotros:** `futbol cuotas` muestra al lado de cada jugador la probabilidad implícita de bet365 y su "L5" (1+ al
arco en sus últimos 5 de titular), cuando hay datos recientes. El modelo de remates (`futbol partido`) es la versión
con más cuidado estadístico.

## 6. Cómo quitar el margen

La literatura muestra que el método "power" y el de Shin corrigen mejor el sesgo favorito–batacazo que repartir el
margen en proporción
([Clarke 2017](https://www.sciencepublishinggroup.com/article/10.11648/j.ajss.20170506.12),
[Ann. Oper. Res. 2022](https://link.springer.com/article/10.1007/s10479-022-04722-3),
[arXiv 2026](https://arxiv.org/pdf/2604.17194),
[Wikipedia](https://en.wikipedia.org/wiki/Favourite-longshot_bias)).

**Lo comprobamos** con 56.537 partidos y las cuotas 1X2 de Pinnacle (`research/devig_metodos.py`):

| Método | Log-loss | Batacazos (cuota ≥ 6): dice / pasó |
|---|---:|---:|
| Multiplicativo | 0,98161 | 11,36 % / 10,36 % |
| **Power** | **0,98134** | **10,66 % / 10,36 %** |
| Shin | 0,98139 | 10,84 % / 10,36 % |

Power es el método por defecto desde ahora.

## 7. Apps de pronósticos para Argentina

FootyStats, BetAnalysis, BetAll, Mr Tipster y otras dan estadísticas y "tips", casi ninguna enfocada en la Liga
Profesional, y sin verificación independiente de aciertos
([FootyStats](https://apps.apple.com/MX/app/id1590091942),
[BetAnalysis](https://apps.apple.com/mx/app/betanalysis/id1501302697),
[BetAll](https://apps.apple.com/us/app/betall-ai%EA%B8%B0%EB%B0%98-%EC%8A%A4%ED%8F%AC%EC%B8%A0-%EB%B0%B0%ED%8C%85-%EB%86%92%EC%9D%80-%EC%A0%95%ED%99%95%EB%8F%84-%EC%98%88%EC%B8%A1/id1447633582?l=es-MX),
[Mr Tipster](https://apps.apple.com/es/app/mr-tipster/id6743175802),
[Match Analytix](https://apps.apple.com/es/app/id1615048439)).

## Lo que estas apps no dicen

- Si una estrategia gana de verdad, la casa limita la cuenta. Es parte del costo.
- Ninguna publica un historial verificado de sus usuarios. Las tasas de "70 % de valor de cierre" que se ven son
  autodeclaradas.
- En nuestra historia (`RESULTADOS-apuestas-deportivas.md`), bet365 contra Pinnacle no mostró una ganancia
  confirmada. Por eso todo pasa primero por papel y por el valor de cierre.
