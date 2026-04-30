import base64
from pathlib import Path
import streamlit as st
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

    st.markdown('<div class="sb-label">Conversación</div>', unsafe_allow_html=True)

    if st.button("＋  Nueva consulta"):
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
with st.expander("⚙️  ¿Cómo está construido y cómo funciona el sistema?"):
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
    <span class="tc-role">Motor de IA · modelos especializados por tarea</span>
  </div>

  <div class="tech-card">
    <span class="tc-icon">🔢</span>
    <span class="tc-name">text-embedding-004</span>
    <span class="tc-role">Embeddings de 768 dim. para búsqueda semántica de síntomas</span>
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
    <div class="step-num">1</div>
    <div class="step-body">
      <strong>Clasificación de intención <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>El mensaje del usuario se clasifica como <em>SALUDO</em>, <em>FUNCIONALIDAD</em> o
      <em>CONSULTA MÉDICA</em>. Si no es una consulta médica, un agente conversacional responde
      de forma directa y el flujo termina aquí.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">2</div>
    <div class="step-body">
      <strong>Extracción de síntomas <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>Un modelo extrae los síntomas mencionados y les asigna una <em>intensidad</em>
      (0.7 leve · 1.0 normal · 1.35 fuerte) a partir de adjetivos como "mucho", "apenas", etc.
      Los síntomas se acumulan a lo largo de toda la conversación.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">3</div>
    <div class="step-body">
      <strong>Búsqueda vectorial en Neo4j <span class="step-badge badge-teal">text-embedding-004 + Neo4j</span></strong>
      <span>Cada síntoma se convierte en un vector de 768 dimensiones y se compara contra el
      índice <code>sintoma_embeddings</code> del grafo. El score final pondera
      <em>probabilidad de presencia × intensidad del paciente × frecuencia poblacional</em> de la
      enfermedad. Si la búsqueda vectorial no encuentra nada, se usa un fallback
      Text-to-Cypher.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">4</div>
    <div class="step-body">
      <strong>Evaluación diagnóstica <span class="step-badge badge-blue">Gemini Lite</span></strong>
      <span>Un modelo evaluador analiza los candidatos ordenados por score y devuelve
      <code>DECISION: &lt;enfermedad&gt;</code> si hay un ganador claro, o
      <code>DIFERENCIAL: &lt;Enf A&gt;, &lt;Enf B&gt;</code> si compiten varias.
      Los síntomas descartados se usan para eliminar candidatas.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">5a</div>
    <div class="step-body">
      <strong>Diagnóstico diferencial — pregunta de descarte <span class="step-badge badge-teal">Gemini Lite</span></strong>
      <span>Cuando hay empate, se consultan todos los síntomas de cada candidata en Neo4j y
      un selector elige el síntoma con mayor <em>poder diferenciador</em> (presente en algunas
      candidatas pero ausente en otras). El asistente pregunta al paciente si lo experimenta y
      guarda el contexto para el siguiente turno.</span>
    </div>
  </div>

  <div class="flow-step">
    <div class="step-num">5b</div>
    <div class="step-body">
      <strong>Redacción de la respuesta final <span class="step-badge badge-green">Gemini Flash</span></strong>
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
        with st.spinner("Analizando tu consulta…"):
            respuesta, st.session_state.contexto_diferencial = asistente.preguntar(
                prompt, st.session_state.mensajes, st.session_state.contexto_diferencial
            )
        st.markdown(respuesta)
        st.session_state.mensajes.append({"role": "assistant", "content": respuesta})