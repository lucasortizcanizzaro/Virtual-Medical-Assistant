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
            respuesta = asistente.preguntar(prompt, st.session_state.mensajes)
        st.markdown(respuesta)
        st.session_state.mensajes.append({"role": "assistant", "content": respuesta})