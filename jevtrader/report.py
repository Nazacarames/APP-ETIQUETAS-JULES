"""Reporte HTML autocontenido (sin dependencias) + JSON con los resultados."""
from __future__ import annotations

import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COLORS = ["#8a8f98", "#2f6fdb", "#d9822b"]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.1f}%" if isinstance(x, (int, float)) and math.isfinite(x) else "—"


def _fmt_num(x: float) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) and math.isfinite(x) else "∞"


def _svg_curves(curves: list[tuple[str, list[tuple[int, float]]]], w: int = 900, h: int = 320) -> str:
    pts_all = [v for _, c in curves for _, v in c if v > 0]
    t_all = [t for _, c in curves for t, _ in c]
    lo, hi = math.log(min(pts_all)), math.log(max(pts_all))
    t0, t1 = min(t_all), max(t_all)
    pad = 40

    def xy(t: int, v: float) -> str:
        x = pad + (t - t0) / (t1 - t0 or 1) * (w - 2 * pad)
        y = h - pad - (math.log(v) - lo) / (hi - lo or 1) * (h - 2 * pad)
        return f"{x:.1f},{y:.1f}"

    lines = []
    for k, (name, c) in enumerate(curves):
        step = max(1, len(c) // 600)
        pts = " ".join(xy(t, v) for t, v in c[::step] if v > 0)
        lines.append(f'<polyline fill="none" stroke="{COLORS[k % 3]}" stroke-width="2" points="{pts}"><title>{html.escape(name)}</title></polyline>')
    legend = "".join(
        f'<span style="color:{COLORS[k % 3]}">■</span> {html.escape(n)} &nbsp; ' for k, (n, _) in enumerate(curves))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Curvas de capital (escala log)">'
            + "".join(lines) + f'</svg><div class="legend">{legend} (escala logarítmica)</div>')


def build_payload(meta: dict, results: list, segments: dict[str, dict[str, dict]], veto: dict,
                  decisions: list[dict]) -> dict[str, Any]:
    def clean(d: dict) -> dict:
        return {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in d.items()}

    return {
        "meta": meta,
        "results": [{"name": r.name, "metrics": clean(r.metrics), "jev_calls": r.jev_calls,
                     "equity": [[t, round(v, 2)] for t, v in r.equity]} for r in results],
        "segments": {seg: {name: clean(m) for name, m in rows.items()} for seg, rows in segments.items()},
        "veto": veto,
        "decisions": decisions,
    }


def write_report(path: str | Path, payload: dict) -> Path:
    meta = payload["meta"]
    rows = []
    for seg, table in payload["segments"].items():
        for name, m in table.items():
            rows.append(
                f"<tr><td>{html.escape(seg)}</td><td>{html.escape(name)}</td>"
                f"<td>{_fmt_pct(m.get('total_return'))}</td><td>{_fmt_pct(m.get('cagr'))}</td>"
                f"<td>{_fmt_pct(m.get('max_drawdown'))}</td><td>{_fmt_num(m.get('sharpe') or 0)}</td>"
                f"<td>{m.get('trades', 0)}</td><td>{_fmt_pct(m.get('win_rate') or 0)}</td>"
                f"<td>{_fmt_num(m.get('profit_factor') if m.get('profit_factor') is not None else float('inf'))}</td>"
                f"<td>{_fmt_pct(m.get('exposure') or 0)}</td></tr>")
    curves = [(r["name"], [(t, v) for t, v in r["equity"]]) for r in payload["results"]]
    v = payload["veto"]
    dec_rows = []
    for d in payload["decisions"][-25:]:
        ans = d.get("answers", {})
        reg = ans.get("regime", {})
        setup = ans.get("setup_quality", {})
        dec_rows.append(
            f"<tr><td>{html.escape(d['date'])}</td><td>{html.escape(d.get('action', ''))}</td>"
            f"<td>{html.escape(str(reg.get('value', '—')))} ({reg.get('confidence', 0):.2f})</td>"
            f"<td>{setup.get('value', 0):.2f}</td>"
            f"<td>{html.escape('; '.join(d.get('reasons', [])))}</td>"
            f"<td>{_fmt_pct(d['shadow_ret']) if d.get('shadow_ret') is not None else '—'}</td></tr>")
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Reporte Jev Trader</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:16px;color:#1d1f23;background:#fff}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 24px}}th,td{{padding:6px 8px;border-bottom:1px solid #e3e5e8;text-align:right}}
th:first-child,td:first-child,td:nth-child(2){{text-align:left}}.legend{{font-size:13px;color:#555}}
.warn{{background:#fff6e5;border:1px solid #f0d9a8;padding:10px 14px;border-radius:8px}}
.scroll{{overflow-x:auto}}
</style></head><body>
<h1>Jev Trader — backtest {html.escape(meta['symbol'])} {html.escape(meta['interval'])}</h1>
<p>{html.escape(meta['start'])} → {html.escape(meta['end'])} · holdout desde {html.escape(meta['holdout_start'])} ·
juez: <b>{html.escape(meta['judge_model'])}</b> · costos {meta['fee_bps']} bps + {meta['slippage_bps']} bps slippage por lado.</p>
<p class="warn">{html.escape(meta['disclaimer'])}</p>
{_svg_curves(curves)}
<h2>Métricas</h2><div class="scroll"><table><tr><th>Tramo</th><th>Variante</th><th>Retorno</th><th>CAGR</th><th>Máx. DD</th>
<th>Sharpe</th><th>Trades</th><th>% ganadores</th><th>Profit factor</th><th>Exposición</th></tr>{''.join(rows)}</table></div>
<h2>¿Ayudan los vetos?</h2>
<p>Señales: {v['signals']} · tomadas: {v['taken']} (ret. medio {_fmt_pct(v['taken_avg_ret'])}, ganadoras {_fmt_pct(v['taken_win_rate'])})
· vetadas: {v['vetoed']} (ret. medio {_fmt_pct(v['vetoed_avg_ret'])}, ganadoras {_fmt_pct(v['vetoed_win_rate'])}).
Si las vetadas rinden igual o mejor que las tomadas, el filtro no aporta.</p>
<h2>Últimas decisiones</h2><div class="scroll"><table><tr><th>Fecha</th><th>Acción</th><th>Régimen (conf.)</th><th>Setup 0–2</th><th>Motivo</th><th>Ret. sombra</th></tr>
{''.join(dec_rows)}</table></div>
<p style="color:#777;font-size:12px">Generado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</p>
</body></html>"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc)
    path.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False))
    return path
