"""
tracer.py — Trazabilidad ligera por turno conversacional.

Sin dependencias externas (solo stdlib). Registra spans nombrados
(inicio, duración, inputs/outputs, estado) en un Trace por turno y
genera HTML de un panel Gantt para st.markdown(..., unsafe_allow_html=True).

Uso típico en consultas.py:
    import tracer as _tracer

    _tracer.new_trace(texto_usuario)           # al inicio de preguntar()
    _tracer.start_span("llm1", "Analizador", "llm", {"chars": 80})
    ...
    _tracer.end_span("llm1", {"intencion": "CONSULTA"})
    ...
    _tracer.finish_trace()                     # antes de cada return final
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ── Paleta de colores por tipo de span ──────────────────────────────────────
_COLORS: dict[str, str] = {
    "regex":  "#6366f1",   # índigo  — ruta rápida sin LLM
    "llm":    "#0891b2",   # cian    — llamadas a Gemini
    "embed":  "#7c3aed",   # violeta — generación de embeddings
    "neo4j":  "#059669",   # verde   — consultas a Neo4j
    "filter": "#d97706",   # ámbar   — filtros y lógica de descarte
    "logic":  "#475569",   # gris    — lógica interna
}
_DEFAULT_COLOR = "#94a3b8"


@dataclass
class Span:
    name:    str              # clave única dentro del trazo
    label:   str              # texto visible en el panel
    kind:    str              # clave de _COLORS
    t_start: float
    t_end:   float = 0.0
    inputs:  dict  = field(default_factory=dict)
    outputs: dict  = field(default_factory=dict)
    status:  str   = "ok"    # "ok" | "error" | "skip"

    @property
    def duration_ms(self) -> float:
        end = self.t_end if self.t_end else time.time()
        return max((end - self.t_start) * 1000, 0.0)

    @property
    def color(self) -> str:
        return _COLORS.get(self.kind, _DEFAULT_COLOR)


@dataclass
class Trace:
    trace_id: str
    query:    str           # primeros 120 chars del mensaje del usuario
    t_start:  float
    t_end:    float       = 0.0
    spans:    list[Span]  = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        end = self.t_end if self.t_end else time.time()
        return max((end - self.t_start) * 1000, 1.0)

    def get_span(self, name: str) -> Span | None:
        return next((s for s in self.spans if s.name == name), None)

    @property
    def llm_calls(self) -> int:
        return sum(1 for s in self.spans if s.kind == "llm" and s.status == "ok")

    @property
    def neo4j_calls(self) -> int:
        return sum(1 for s in self.spans if s.kind == "neo4j" and s.status != "skip")


# ── Estado de módulo ─────────────────────────────────────────────────────────
_current: Trace | None       = None
_recent:  deque[Trace]       = deque(maxlen=20)
_open:    dict[str, Span]    = {}   # spans aún no cerrados


# ── API pública ──────────────────────────────────────────────────────────────

def new_trace(query: str) -> Trace:
    """Inicia un trazo nuevo. Si había uno activo, lo finaliza automáticamente."""
    global _current, _open
    if _current is not None:
        _current.t_end = _current.t_end or time.time()
        _recent.append(_current)
    _current = Trace(
        trace_id=str(uuid.uuid4())[:8].upper(),
        query=query[:120],
        t_start=time.time(),
    )
    _open = {}
    return _current


def start_span(name: str, label: str, kind: str = "logic",
               inputs: dict | None = None) -> Span:
    """Abre un span y lo añade al trazo activo."""
    span = Span(
        name=name, label=label, kind=kind,
        t_start=time.time(),
        inputs=inputs or {},
    )
    if _current is not None:
        _current.spans.append(span)
    _open[name] = span
    return span


def end_span(name: str, outputs: dict | None = None,
             status: str = "ok") -> None:
    """Cierra un span abierto (por nombre)."""
    span = _open.pop(name, None)
    if span is None and _current is not None:
        span = _current.get_span(name)
    if span is not None:
        span.t_end = time.time()
        if outputs:
            span.outputs = outputs
        span.status = status


def skip_span(name: str, label: str, kind: str = "logic") -> None:
    """Registra un span como omitido (ruta no ejecutada en este turno)."""
    span = Span(
        name=name, label=label, kind=kind,
        t_start=time.time(), t_end=time.time(), status="skip",
    )
    if _current is not None:
        _current.spans.append(span)


def finish_trace() -> Trace | None:
    """Cierra el trazo activo y lo guarda en el historial reciente."""
    global _current
    if _current is None:
        return None
    _current.t_end = time.time()
    for span in _open.values():
        span.t_end = _current.t_end
    _open.clear()
    _recent.append(_current)
    finished = _current
    _current = None
    return finished


def get_last_trace() -> Trace | None:
    """Devuelve el trazo más reciente (en curso o ya finalizado)."""
    if _current is not None:
        return _current
    return _recent[-1] if _recent else None


def get_recent_traces() -> list[Trace]:
    return list(_recent)


# ── Renderizado HTML ─────────────────────────────────────────────────────────

def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _esc(v: Any) -> str:
    """Escape básico para atributos HTML + truncado."""
    s = str(v)
    if len(s) > 80:
        s = s[:77] + "…"
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def render_trace_html(trace: Trace) -> str:
    """Genera HTML completo del panel Gantt para st.markdown(unsafe_allow_html=True)."""
    total = trace.total_ms
    t0    = trace.t_start

    # ── Cabecera ─────────────────────────────────────────────────────────────
    html = (
        '<div style="font-family:\'Courier New\',monospace;font-size:.78rem;'
        'background:#0f172a;border-radius:10px;padding:14px 16px;'
        'color:#e2e8f0;margin:4px 0">'

        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'border-bottom:1px solid #1e293b;padding-bottom:8px;margin-bottom:10px">'
        '<span style="color:#7dd3fc;font-weight:700;font-size:.84rem">'
        f'⚡ TRACE <span style="color:#fbbf24">{trace.trace_id}</span></span>'
        '<span style="color:#94a3b8;font-size:.75rem">'
        f'{_fmt_ms(total)}&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'{trace.llm_calls} LLM call{"s" if trace.llm_calls != 1 else ""}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'{trace.neo4j_calls} Neo4j call{"s" if trace.neo4j_calls != 1 else ""}'
        '</span></div>'

        '<div style="color:#64748b;margin-bottom:13px;font-size:.74rem">'
        f'<span style="color:#475569">query › </span>'
        f'<span style="color:#cbd5e1">{_esc(trace.query)}</span></div>'
    )

    # ── Leyenda de colores ────────────────────────────────────────────────────
    legend_items = [
        ("#0891b2", "LLM"),
        ("#7c3aed", "Embed"),
        ("#059669", "Neo4j"),
        ("#d97706", "Filtro"),
        ("#6366f1", "Regex"),
    ]
    legend_html = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{c};display:inline-block"></span>'
        f'<span style="color:#64748b">{n}</span></span>'
        for c, n in legend_items
    )
    html += (
        f'<div style="margin-bottom:10px;font-size:.70rem">{legend_html}</div>'
    )

    # ── Filas Gantt ───────────────────────────────────────────────────────────
    for span in trace.spans:
        offset = min(((span.t_start - t0) / (total / 1000)) * 100, 97.0)
        width  = min((span.duration_ms / total) * 100, 100.0 - offset)
        width  = max(width, 0.5)

        opacity     = "0.40" if span.status == "skip" else "1"
        status_icon = "✓" if span.status == "ok" else ("⊘" if span.status == "skip" else "✗")
        icol        = (
            "#4ade80" if span.status == "ok"
            else "#475569" if span.status == "skip"
            else "#f87171"
        )

        # Tooltip: inputs arriba, outputs abajo
        tip_parts = [f"{k}: {_esc(v)}" for k, v in span.inputs.items()]
        if span.outputs:
            tip_parts += ["──"] + [f"{k}: {_esc(v)}" for k, v in span.outputs.items()]
        tip = " | ".join(tip_parts)

        html += (
            f'<div style="display:flex;align-items:center;gap:7px;'
            f'margin-bottom:5px;opacity:{opacity}" title="{tip}">'

            f'<span style="color:{icol};width:10px;text-align:center;'
            f'font-size:.72rem">{status_icon}</span>'

            f'<span style="width:200px;color:#94a3b8;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;font-size:.73rem">'
            f'{span.label}</span>'

            f'<div style="flex:1;position:relative;height:14px;'
            f'background:#1e293b;border-radius:3px">'
            f'<div style="position:absolute;left:{offset:.1f}%;width:{width:.1f}%;'
            f'height:100%;background:{span.color};border-radius:3px;opacity:.85">'
            f'</div></div>'

            f'<span style="width:54px;text-align:right;color:#64748b;'
            f'font-size:.71rem">{_fmt_ms(span.duration_ms)}</span>'
            f'</div>'
        )

    html += '</div>'
    return html
