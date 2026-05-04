import base64
from pathlib import Path
import streamlit as st
import consultas as asistente_module
from consultas import AsistenteMedico

_ASSETS = Path(__file__).parent / "assets"

def _logo_b64() -> str:
    p = _ASSETS / "logo.png"
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return ""

def _load_css() -> None:
    css = (_ASSETS / "style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# ── Configuración de la página ────────────────────────────────────────────────
st.set_page_config(
    page_title="MEDIC-AI · Asistente Médico",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS personalizado ────────────────────────────────────────────────────────
_load_css()

# ── Asistente (cacheado) ──────────────────────────────────────────────────────
@st.cache_resource
def crear_asistente():
    return AsistenteMedico()

asistente = crear_asistente()

# ── Estado de la API (cacheado 60 s) ─────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _verificar_estado_api() -> bool:
    """Resultado cacheado 60 s para no saturar la API en cada render."""
    return asistente_module.verificar_api(asistente_module._get_secret("GEMINI_API_KEY"))

_api_ok = _verificar_estado_api()

# ── Estado inicial ────────────────────────────────────────────────────────────
if "mensajes" not in st.session_state:
    st.session_state.mensajes = [
        {
            "role": "assistant",
            "content": (
                "¡Hola! Soy **MediAI**, tu asistente de orientación médica basado en evidencia.\n\n"
                "Puedo ayudarte a relacionar tus síntomas con posibles condiciones y sugerirte la "
                "especialidad médica más adecuada.\n\n"
                "> ⚕️ *Soy una herramienta de orientación. Siempre consultá con un médico "
                "para un diagnóstico definitivo.*\n\n"
                "¿Qué síntomas estás experimentando?"
            ),
        }
    ]

if "contexto_diferencial" not in st.session_state:
    st.session_state.contexto_diferencial = None

if "ultimo_timing" not in st.session_state:
    st.session_state.ultimo_timing = []

# ── Sidebar ───────────────────────────────────────────────────────────────────
_logo = _logo_b64()
_logo_html = (
    f'<img src="data:image/png;base64,{_logo}" />'
    if _logo else
    '<span style="font-size:3rem">&#x1FA7A;</span>'
)
with st.sidebar:
    st.markdown(f"""
    <div class="sb-logo">
        {_logo_html}
        <span class="brand">MEDIC-AI</span>
        <span class="tagline">Asistente Médico Generativo</span>
    </div>
    <hr class="sb-divider">
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="status-pill">
        <span class="pulse-dot"></span>
        Sistema activo
    </div>
    """, unsafe_allow_html=True)

    if _api_ok:
        st.markdown("""
    <div class="status-pill">
        <span class="pulse-dot"></span>
        API activa
    </div>
    """, unsafe_allow_html=True)
    else:
        st.markdown("""
    <div class="status-pill status-pill--error">
        <span class="pulse-dot pulse-dot--error"></span>
        API inactiva
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sb-label">Conversación</div>', unsafe_allow_html=True)

    if st.button("+  Nueva consulta"):
        st.session_state.mensajes = [
            {
                "role": "assistant",
                "content": (
                    "Chat reiniciado. ¡Listo para una nueva consulta!\n\n"
                    "¿Qué síntomas estás experimentando?"
                ),
            }
        ]
        st.session_state.contexto_diferencial = None
        st.rerun()

    n_total = len(st.session_state.mensajes)
    n_user  = sum(1 for m in st.session_state.mensajes if m["role"] == "user")
    st.markdown(
        f'<div class="sb-counter">'
        f'{n_total} mensaje{"s" if n_total != 1 else ""} &nbsp;·&nbsp; '
        f'{n_user} consulta{"s" if n_user != 1 else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("""
    <div class="sb-card" style="border-left:3px solid #dc2626;">
        <h4>⚠️ Aviso</h4>
        <p>Este asistente provee orientación general y no reemplaza el diagnóstico de un médico certificado.</p>
    </div>
    <div class="sb-card" style="border-left:3px solid #0891b2;">
        <h4>🔍 Puedo ayudarte con</h4>
        <p>
            • Relacionar síntomas con enfermedades<br>
            • Sugerir la especialidad indicada<br>
            • Orientar sobre nivel de gravedad<br>
            • Responder dudas sobre condiciones
        </p>
    </div>
    """, unsafe_allow_html=True)

# ── Header principal ──────────────────────────────────────────────────────────
_hdr_logo = (
    f'<img class="hdr-logo" src="data:image/png;base64,{_logo}" />'
    if _logo else
    '<span style="font-size:2.8rem">&#x1FA7A;</span>'
)
st.markdown(f"""
<div class="main-hdr">
    {_hdr_logo}
    <div>
        <h1>MEDIC-AI</h1>
        <p>Sistema de Orientación Médica con Inteligencia Artificial</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Sección: cómo está construido / flujo del sistema ────────────────────────
with st.expander("¿Cómo está construido y cómo funciona el sistema?"):
    st.markdown("""
<div class="arch-section">

<h4>Stack tecnológico</h4>
<div class="tech-grid">

  <div class="tech-card">
    <span class="tc-icon">🌐</span>
    <span class="tc-name">Streamlit</span>
    <span class="tc-role">Interfaz web · gestión del estado de la conversación</span>
  </div>

  <div class="tech-card">
    <span class="tc-icon">✨</span>
    <span class="tc-name">Google Gemini</span>
    <span class="tc-role">Motor de IA · agentes especializados por tarea (gemini-3.1-flash-lite)</span>
  </div>

  <div class="tech-card">
    <span class="tc-icon">🔢</span>
    <span class="tc-name">gemini-embedding-001</span>
    <span class="tc-role">Embeddings de 768 dim. vía REST para búsqueda semántica de síntomas</span>
  </div>

  <div class="tech-card">
    <span class="tc-icon">🗄️</span>
    <span class="tc-name">Neo4j</span>
    <span class="tc-role">Base de datos de grafos · nodos Enfermedad · Sintoma · Especialidad</span>
  </div>

</div>

<h4>Flujo de una consulta</h4>
<div class="flow-steps">

  <div class="flow-step">
    <div class="step-num">0</div>
    <div class="step-body">
      <strong>Ruta ultra-rápida — detección por regex <span class="step-badge badge-green">0 llamadas LLM</span></strong>
      <span>Si el mensaje es un saludo puro (hola, gracias, chau…) sin ninguna palabra médica,
      se responde de forma instantánea sin consumir la API. El flujo termina aquí.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">1</div>
    <div class="step-body">
      <strong>Análisis unificado: intención + síntomas <span class="step-badge badge-blue">Gemini Lite · 1 llamada</span></strong>
      <span>Una sola llamada LLM clasifica la intención del mensaje (<em>SALUDO</em>,
      <em>FUNCIONALIDAD</em> o <em>CONSULTA</em>) y extrae simultáneamente los síntomas con su
      intensidad (0.7 leve · 1.0 normal · 1.35 fuerte). Si no es consulta médica, un agente
      conversacional responde y el flujo termina.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">2</div>
    <div class="step-body">
      <strong>Resolución del contexto diferencial previo</strong>
      <span>Si en el turno anterior se preguntó por un síntoma de descarte, se interpreta la
      respuesta del paciente (sí/no) y se actualiza la lista de síntomas confirmados, negados y
      acumulados a lo largo de toda la conversación.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">3</div>
    <div class="step-body">
      <strong>Búsqueda en tres capas <span class="step-badge badge-teal">gemini-embedding-001 + Neo4j</span></strong>
      <span>
        <b>Capa 1 — Vectorial:</b> cada síntoma acumulado se convierte en un vector de 768 dim. y
        se consulta el índice <code>sintoma_embeddings</code>. El score pondera
        <em>probabilidad de presencia × intensidad × frecuencia poblacional</em>.<br>
        <b>Capa 2 — Nombre exacto:</b> si la búsqueda vectorial no devuelve resultados, se busca
        por coincidencia exacta de nombre en el grafo.<br>
        <b>Capa 3 — Text-to-Cypher:</b> solo para consultas informativas sin síntomas (ej: "¿qué
        enfermedades trata un cardiólogo?"). Genera Cypher, valida que sea solo lectura y lo ejecuta.
      </span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">4</div>
    <div class="step-body">
      <strong>Evaluación diagnóstica <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>Un modelo evaluador analiza los candidatos ordenados por score. Devuelve
      <code>DECISION: &lt;enfermedad&gt;</code> si hay un ganador claro, o
      <code>DIFERENCIAL: &lt;Enf A&gt;, &lt;Enf B&gt;</code> si compiten varias.
      Los síntomas negados por el paciente se usan para descartar candidatas.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">5a</div>
    <div class="step-body">
      <strong>Diagnóstico diferencial — pregunta de descarte <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>Cuando hay empate, se consultan en Neo4j todos los síntomas de cada candidata.
      Un selector LLM elige el síntoma con mayor <em>poder diferenciador</em> (presente en
      algunas candidatas pero ausente en otras) y el asistente se lo pregunta al paciente.
      El contexto se guarda para el siguiente turno.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">5b</div>
    <div class="step-body">
      <strong>Redacción de la respuesta final <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>Con la enfermedad decidida, un modelo redactor convierte los datos crudos del grafo
      (gravedad, especialidad, síntomas asociados) en una respuesta empática en lenguaje natural,
      recordando siempre consultar a un médico para un diagnóstico definitivo.</span>
    </div>
  </div>

</div>
</div>
""", unsafe_allow_html=True)

# ── Historial de mensajes ─────────────────────────────────────────────────────
for msj in st.session_state.mensajes:
    with st.chat_message(msj["role"]):
        st.markdown(msj["content"])

# ── Input y procesamiento ─────────────────────────────────────────────────────
if prompt := st.chat_input("Describí tus síntomas...  (ej: tengo fiebre y dolor de cabeza)"):
    st.session_state.mensajes.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        import threading as _threading
        import time as _time

        # Etapas: (fracción de la barra al inicio de la etapa, texto)
        _ETAPAS = [
            (0.00, "Analizando consulta"),
            (0.15, "Consultando base de datos"),
            (0.25, "Evaluando diagnóstico"),
            (0.50, "Preparando respuesta"),
        ]
        _TOTAL_S = 30.0   # duración esperada en segundos
        _TICK    = 0.12   # intervalo de refresco

        _resultado = [None, None]
        _error     = [None]
        # Capturar los valores del session_state en el hilo principal,
        # ya que st.session_state no es accesible desde hilos secundarios.
        _mensajes_snapshot  = list(st.session_state.mensajes)
        _contexto_snapshot  = st.session_state.contexto_diferencial

        def _ejecutar():
            try:
                _resultado[0], _resultado[1] = asistente.preguntar(
                    prompt, _mensajes_snapshot, _contexto_snapshot
                )
            except Exception as exc:
                _error[0] = exc

        _hilo = _threading.Thread(target=_ejecutar, daemon=True)
        _hilo.start()

        # Un único placeholder — se reemplaza con la respuesta al terminar
        _slot = st.empty()
        _elapsed = 0.0

        while _hilo.is_alive():
            frac = min(_elapsed / _TOTAL_S, 0.97)
            pct  = int(frac * 100)
            label = _ETAPAS[-1][1]
            for i in range(len(_ETAPAS) - 1, -1, -1):
                if frac >= _ETAPAS[i][0]:
                    label = _ETAPAS[i][1]
                    break
            _slot.markdown(
                f"""<div style="display:flex;align-items:center;gap:10px;padding:2px 0">
  <span style="color:#6b7280;font-size:0.85rem;white-space:nowrap">⏳ {label}</span>
  <div style="flex:1;max-width:220px;background:#e5e7eb;border-radius:4px;height:5px">
    <div style="width:{pct}%;height:5px;border-radius:4px;
                background:linear-gradient(90deg,#0891b2,#06b6d4);
                transition:width 0.1s linear"></div>
  </div>
  <span style="color:#9ca3af;font-size:0.75rem;min-width:30px">{pct}%</span>
</div>""",
                unsafe_allow_html=True,
            )
            _time.sleep(_TICK)
            _elapsed += _TICK

        if _error[0]:
            respuesta = str(_error[0])
            st.session_state.contexto_diferencial = None
        else:
            respuesta = _resultado[0]
            st.session_state.contexto_diferencial = _resultado[1]
            _verificar_estado_api.clear()

        # Reemplaza el loader con la respuesta — sin elemento extra
        _slot.markdown(respuesta)

        st.session_state.ultimo_timing = list(asistente_module._timing_log)
        st.session_state.mensajes.append({"role": "assistant", "content": respuesta})

# ── Timing del último turno (fuera del if prompt para persistir en re-renders) ──
if st.session_state.get("ultimo_timing"):
    with st.expander("⏱ Timing", expanded=True):
        st.code("\n".join(st.session_state.ultimo_timing))