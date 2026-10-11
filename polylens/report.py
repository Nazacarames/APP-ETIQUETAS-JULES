"""Informe HTML autocontenido (sin JavaScript ni recursos externos) a partir de los resultados guardados.

Todo texto que viene de Polymarket o de feeds (nombres, títulos, titulares) se escapa: es contenido ajeno.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

SIG_CLASS = {"sólido": "good", "prometedor": "ok", "no se distingue de la suerte": "meh", "negativo": "bad",
             "muestra chica": "meh"}
DELAY_LABEL = {"0": "al instante", "3600": "1 h", "21600": "6 h", "86400": "24 h"}

CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e2dd;--good:#1f7a4d;--ok:#8a6d00;
--bad:#b3261e;--meh:#6b6b66;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#ecebe6;--muted:#a3a29b;
--card:#1e1e1c;--line:#33322f;--good:#5ccf93;--ok:#e2c04a;--bad:#ff8a80;--meh:#a3a29b;--accent:#8fb0ff}}
:root[data-theme="dark"]{--bg:#151514;--fg:#ecebe6;--muted:#a3a29b;--card:#1e1e1c;--line:#33322f;--good:#5ccf93;
--ok:#e2c04a;--bad:#ff8a80;--meh:#a3a29b;--accent:#8fb0ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 8px}p.sub{color:var(--muted);margin:0 0 16px}
.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);padding:12px 14px;
border-radius:6px;margin:12px 0}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:13px}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;min-width:720px;font-size:13.5px}th,td{padding:7px 9px;text-align:left;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}tr:last-child td{border-bottom:0}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;border:1px solid currentColor;
white-space:nowrap}.good{color:var(--good)}.ok{color:var(--ok)}.bad{color:var(--bad)}.meh{color:var(--meh)}
ul.flags{margin:0;padding-left:16px;color:var(--muted);font-size:12.5px}a{color:var(--accent)}
.muted{color:var(--muted)}table.wide{min-width:1080px}table.wide td:last-child{min-width:300px}
td.n .muted{font-size:12px}
"""


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def safe_url(u) -> str:
    """Solo enlaces http(s): un feed podría traer 'javascript:...'."""
    u = str(u or "").strip()
    return u if u.lower().startswith(("https://", "http://")) else ""


def pct(x, signed: bool = True) -> str:
    if x is None:
        return "–"
    return f"{x:+.1%}" if signed else f"{x:.0%}"


def usd(x) -> str:
    return "–" if x is None else f"{x:,.0f}"


def num(x, d: int = 2) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def tag(label: str) -> str:
    return f'<span class="tag {SIG_CLASS.get(label, "meh")}">{e(label)}</span>'


def profile_link(p: dict) -> str:
    name = p.get("name") or (p.get("user") or "")[:10]
    return f'<a href="https://polymarket.com/profile/{e(p.get("user"))}" rel="noopener">{e(name)}</a>'


def table(head: list[str], rows: list[str], cls: str = "") -> str:
    ths = "".join(f"<th>{h}</th>" for h in head)
    return (f'<div class="tw"><table class="{cls}"><thead><tr>{ths}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def row(cells: list[str], numeric: set[int] = frozenset()) -> str:
    return "<tr>" + "".join(f'<td class="n">{c}</td>' if i in numeric else f"<td>{c}</td>"
                            for i, c in enumerate(cells)) + "</tr>"


def section_scan(scan: dict) -> str:
    m, profiles = scan["meta"], scan["profiles"]
    counts: dict[str, int] = {}
    for p in profiles:
        counts[p["significance"]] = counts.get(p["significance"], 0) + 1
    th = m.get("thresholds", {})
    kpis = "".join(f'<div class="kpi"><b class="{SIG_CLASS.get(k, "meh")}">{counts.get(k, 0)}</b><span>{e(k)}</span></div>'
                   for k in ("sólido", "prometedor", "no se distingue de la suerte", "negativo", "muestra chica"))
    rows = []
    for p in profiles:
        rows.append(row([
            profile_link(p), tag(p["significance"]), str(p["n"]), pct(p["win_rate"], False), pct(p["roi"]),
            num(p["t_stat"]), usd(p["total_pnl"]), usd(p["board_pnl"]), pct(p["share_favorites"], False),
            pct(p["share_longshots"], False), num(p["trades_per_day"], 0), num(p.get("window_days"), 0),
            "<ul class='flags'>" + "".join(f"<li>{e(f)}</li>" for f in p.get("flags", [])) + "</ul>",
        ], numeric={2, 3, 4, 5, 6, 7, 8, 9, 10, 11}))
    head = ["Trader", "Veredicto", "Posiciones", "Aciertos", "ROI", "t", "Ganancia (ventana)", "Ganancia (ranking)",
            "En casi seguros", "En batacazos", "Ops/día", "Días", "Alertas"]
    return f"""
<h2>Ranking por consistencia</h2>
<p class="sub">Top {e(m['top'])} del ranking de Polymarket ({e(m['period'])}, {e(m['category'])}), reordenado por
consistencia en sus posiciones con resultado de los últimos {e(m['days'])} días. Umbrales con {e(m['analyzed'])}
traders mirados: el mejor t que daría el azar ≈ {num(th.get('azar'))}; "sólido" exige t ≥ {num(th.get('solido'))}.</p>
<div class="kpis">{kpis}</div>
<div style="height:12px"></div>
{table(head, rows, 'wide')}
"""


def section_categories(scan: dict) -> str:
    good = [p for p in scan["profiles"] if p["significance"] in ("sólido", "prometedor") and p.get("categories")]
    if not good:
        return ""
    rows = []
    for p in good:
        cats = "; ".join(f"{e(c)}: {v['n']} pos., ROI {pct(v['roi'])}" for c, v in list(p["categories"].items())[:4])
        rows.append(row([profile_link(p), tag(p["significance"]), cats]))
    return f"""
<h2>Dónde ganan los que pasaron el filtro</h2>
<p class="sub">Categoría de cada mercado según {e(scan['meta'].get('categorizer') or 'palabras clave')}.</p>
{table(["Trader", "Veredicto", "Categorías (por dinero puesto)"], rows)}
"""


def section_flows(flows: dict) -> str:
    rows = []
    for m in flows["markets"][:40]:
        names = ", ".join(e(t["name"]) for t in m["traders"][:5])
        rows.append(row([e(m["title"]), e(m["outcome"]), str(m["n"]), names, usd(m["value"]), num(m["current_price"]),
                         num(m.get("avg_entry")), pct(m["upside_if_wins"]),
                         '<span class="tag bad">en disputa</span>' if m["disputed"] else ""],
                        numeric={2, 4, 5, 6, 7}))
    head = ["Mercado", "Resultado", "Traders", "Quiénes", "Valor USD", "Precio hoy", "Entrada prom.",
            "Paga si gana", ""]
    return f"""
<h2>Dónde están hoy</h2>
<p class="sub">Posiciones abiertas de {len(flows['traders'])} traders seleccionados. "En disputa": otro de ellos
apuesta al resultado contrario en el mismo mercado. Esto no es una recomendación.</p>
{table(head, rows)}
"""


def _delay_cells(s: dict) -> list[str]:
    cells = []
    for d in ("0", "3600", "21600", "86400"):
        v = s.get("by_delay", {}).get(d)
        if not v:
            cells.append("–")
            continue
        ci = v.get("ci95")
        ci_txt = f"<br><span class='muted'>[{pct(ci[0])}, {pct(ci[1])}]</span>" if ci else ""
        cells.append(f"{pct(v['mean'])} <span class='muted'>(n={v['n']})</span>{ci_txt}")
    return cells


def section_study(study: dict) -> str:
    m = study["meta"]
    rows = []
    for t in study["traders"]:
        s = t["summary"]
        tr = s.get("trader") or {}
        rows.append(row([profile_link(t), tag(t.get("significance") or ""), str(s["n"]), pct(tr.get("mean")),
                         *_delay_cells(s), e(s["verdict"])], numeric={2, 3, 4, 5, 6, 7}))
    p = study["pooled"]
    pt = p.get("trader") or {}
    rows.append(row(["<b>Todos juntos</b>", "", str(p["n"]), pct(pt.get("mean")), *_delay_cells(p), e(p["verdict"])],
                    numeric={2, 3, 4, 5, 6, 7}))
    head = ["Trader", "Veredicto escaneo", "Compras", "Trader (mantener)"] + \
           [f"Copiador {DELAY_LABEL[d]}" for d in ("0", "3600", "21600", "86400")] + ["Lectura"]
    return f"""
<h2>¿Se puede copiar?</h2>
<p class="sub">Muestra de hasta {e(m['sample'])} compras por trader (≥ {usd(m['min_usd'])} USD) de los últimos
{e(m['days'])} días, en mercados ya resueltos. El copiador compra lo mismo con demora, paga {m['slippage'] * 100:.0f} centavo(s) de
deslizamiento y mantiene hasta la resolución. Retorno promedio por compra y, entre corchetes, intervalo de confianza
del 95 %.</p>
{table(head, rows)}
"""


def section_news(news: dict) -> str:
    if not news.get("matches"):
        return ""
    rows = []
    fav = {"supports": '<span class="tag good">a favor</span>', "against": '<span class="tag bad">en contra</span>',
           "unclear": '<span class="tag meh">no está claro</span>'}
    for r in news["matches"][:40]:
        h, mk = r["headline"], r["market"]
        url = safe_url(h.get("link"))
        link = f'<a href="{e(url)}" rel="noopener">{e(h["title"])}</a>' if url else e(h["title"])
        rows.append(row([link, f"{e(mk['title'])} → <b>{e(mk['outcome'])}</b>", num(r["relevance"]),
                         fav.get(r["favors"], e(r["favors"])), num(r["favors_confidence"])], numeric={2, 4}))
    return f"""
<h2>Noticias que tocan esas apuestas</h2>
<p class="sub">Juez: {e(news['meta'].get('judge'))}. "A favor / en contra" del resultado que tienen los traders
seguidos.</p>
{table(["Titular", "Mercado → resultado", "Relevancia", "Dirección", "Confianza"], rows)}
"""


METHOD = """
<h2>Cómo leer esto</h2>
<div class="note"><ul>
<li><b>El ranking de Polymarket muestra quién ganó mucho, no quién gana seguido.</b> Una sola apuesta grande
pone a cualquiera arriba. Por eso se reordena por consistencia: el estadístico t de los retornos por posición
(recortados a −100 %…+1000 % para que un batacazo no domine).</li>
<li><b>Corrección por mirar a muchos:</b> entre N traders, alguno parece bueno por azar. "Sólido" exige superar
el umbral de Bonferroni al 5 %; "prometedor", el mejor valor esperable por suerte.</li>
<li><b>Posiciones con resultado</b> = cerradas + ganadas sin cobrar + perdidas que se dejaron vencer, en una misma
ventana de tiempo. El costo de cada posición sale del precio promedio que informa la API: en mercados de
"riesgo negativo" (conversiones) puede no coincidir con lo que realmente pagó; el ROI es aproximado.</li>
<li><b>Copiabilidad:</b> muchos ganadores viven de entrar y salir (o de hacer de market maker), no de acertar el
resultado. Si sus compras mantenidas hasta el final no rinden, copiarlas tampoco. La muestra se limita a mercados
ya resueltos, lo que favorece mercados cortos (deportes, cripto diario).</li>
<li>Rendimientos pasados no garantizan nada. Esto es análisis de datos públicos, no una recomendación.</li>
</ul></div>
"""


def render(scan: dict | None, flows: dict | None = None, study: dict | None = None, news: dict | None = None) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"""<h1>Polylens</h1>
<p class="sub">Informe generado {when}. Solo lectura de datos públicos de Polymarket.</p>
<div class="note">Polymarket está bloqueado en Argentina desde marzo de 2026 (orden judicial, ENACOM). Este informe
analiza datos públicos con fines de estudio: no opera, no recomienda operar y no sirve para eludir el bloqueo.</div>"""]
    if scan:
        parts += [section_scan(scan), section_categories(scan)]
    else:
        parts.append('<p class="muted">Todavía no hay un escaneo: corré <code>python3 -m polylens scan</code>.</p>')
    if flows:
        parts.append(section_flows(flows))
    if study:
        parts.append(section_study(study))
    if news:
        parts.append(section_news(news))
    parts.append(METHOD)
    body = "\n".join(p for p in parts if p)
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polylens informe</title><style>{CSS}</style></head>
<body><main>{body}</main></body></html>
"""


def write(path: str | Path, html_text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html_text, encoding="utf-8")
    return p
