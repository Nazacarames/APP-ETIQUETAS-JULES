---
name: polymarket-analysis
description: 'Flujo completo de Polylens para analizar a los mejores traders de Polymarket y sus mercados: escaneo, perfil de una billetera, flujos de smart money, copiabilidad con demora, noticias con Jev e informe. Usala cuando pidan buscar traders con buena tasa de acierto, analizar billeteras o movimientos, encontrar patrones o preguntar si conviene seguir/copiar a alguien en Polymarket.'
---

# Análisis de Polymarket con Polylens

Polylens solo lee datos públicos. No opera, no maneja billeteras y no ayuda a eludir el bloqueo de Polymarket
en Argentina (vigente desde marzo de 2026).

## Pasos
1. Tests primero: `python3 -m unittest discover -s tests -t .`. Si fallan, no sigas.
2. Escaneo: `python3 -m polylens scan --period month --top 100` (agregá `--category politics|sports|crypto...`
   para un nicho). Con `--jev` las categorías las decide Jev (tope `--jev-max`, el resto por palabras clave).
3. Flujos: `python3 -m polylens flows` → dónde están hoy los que pasaron el filtro.
4. Copiabilidad: `python3 -m polylens study --top 5` → qué pasa si se copian sus compras con 0, 1, 6 y 24 h
   de demora, manteniendo hasta la resolución.
5. Noticias (opcional): `python3 -m polylens news --rss <url> --rss <url>`.
6. Informe: `python3 -m polylens report --out reports/polylens.html`.

## Cómo interpretar sin engañarse
- **Ranking ≠ habilidad.** El top del ranking está lleno de una o dos apuestas enormes. Mirá el veredicto:
  "sólido" supera Bonferroni al 5 % para los N traders mirados; "prometedor" supera lo que daría el azar.
  "no se distingue de la suerte" es lo más común y es una conclusión válida.
- **Aciertos altos no son ventaja.** Quien compra "casi seguros" a 0,95 acierta el 95 % y puede perder
  plata. Mirá ROI y t junto con `share_favorites` y la peor pérdida.
- **Muchos ganadores no son copiables.** Market makers y traders que entran y salen ganan con el spread o con
  la velocidad, no acertando el resultado. Si "Trader (mantener)" ya es negativo, copiar sus compras pierde.
- **La demora cuesta.** `gap_mean` muestra cuántos centavos se movió el precio después de su compra; si es
  positivo, el mercado ya incorporó la información cuando llegás.
- **Muestras chicas.** Menos de ~20 compras por demora o intervalos de confianza que cruzan 0 → "no
  concluyente". Decilo así, no redondees a "funciona".
- **Persistencia.** Lo más convincente es que un trader siga siendo "sólido" en escaneos de fechas distintas
  (`data/scans/` guarda uno por corrida). Compará antes de concluir.
- **Alertas de información anticipada** (apuestas grandes a precio bajo cerca del cierre que salieron bien) son
  un patrón para mirar de cerca, no una acusación.

## Al reportar
- Decí qué juez se usó (Jev o MockJev) y la ventana de datos.
- Tabla corta: trader, veredicto, posiciones, ROI, t, copiabilidad a 1 h.
- Cerrá con lo que los datos NO permiten decir. No hay recomendaciones de inversión.
