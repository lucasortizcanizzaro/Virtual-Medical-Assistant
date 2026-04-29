import base64
from pathlib import Path
import streamlit as st
from consultas import AsistenteMedico

def _logo_b64() -> str:
    p = Path(__file__).parent / "assets" / "logo.png"
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return ""

# ── Configuración de la página ────────────────────────────────────────────────
st.set_page_config(
    page_title="MediAI · Asistente Médico",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personalizado ─────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ─ Variables ─────────────────────────────────────────────────────────────── */
:root {
    --bg-main:     #f0f5fb;
    --bg-sidebar:  #ffffff;
    --bg-card:     #ffffff;
    --bg-input:    #ffffff;
    --accent:      #2563eb;
    --accent-dim:  rgba(37,99,235,0.08);
    --accent-glow: rgba(37,99,235,0.20);
    --teal:        #0891b2;
    --teal-dim:    rgba(8,145,178,0.08);
    --teal-glow:   rgba(8,145,178,0.20);
    --danger:      #dc2626;
    --text-1:      #0f172a;
    --text-2:      #475569;
    --text-3:      #94a3b8;
    --border:      rgba(0,0,0,0.07);
    --border-acc:  rgba(37,99,235,0.22);
    --r-lg: 18px; --r-md: 12px; --r-sm: 8px;
}

/* ─ Reset global ──────────────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: var(--bg-main) !important;
    color: var(--text-1) !important;
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif !important;
}

/* ─ Ocultar chrome de Streamlit ───────────────────────────────────────────── */
#MainMenu, footer, header { visibility: hidden !important; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* ─ Contenedor principal ─────────────────────────────────────────────────── */
.main .block-container {
    padding-top: 0 !important;
    padding-bottom: 120px !important;
    max-width: 860px !important;
}

/* ─ Sidebar ──────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border) !important;
    box-shadow: 2px 0 16px rgba(0,0,0,0.06) !important;
}
[data-testid="stSidebar"] * { color: var(--text-1) !important; }
[data-testid="stSidebar"] .stButton button,
[data-testid="stSidebar"] .stButton button *,
[data-testid="stSidebar"] .stButton button p { color: #ffffff !important; }

/* ─ Sidebar: logo ────────────────────────────────────────────────────────── */
.sb-logo {
    text-align: center;
    padding: 22px 12px 16px;
}
.sb-logo img {
    width: 150px;
    height: auto;
    display: block;
    margin: 0 auto;
    filter: drop-shadow(0 4px 12px var(--teal-glow));
}
.sb-logo .brand {
    display: block;
    margin-top: 10px;
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: -0.3px;
    background: linear-gradient(100deg, #2563eb 20%, #0891b2 80%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.sb-logo .tagline {
    display: block;
    margin-top: 4px;
    font-size: 0.72rem;
    color: var(--text-3);
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.sb-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 16px 0;
}

/* ─ Status badge ─────────────────────────────────────────────────────────── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: rgba(8,145,178,0.07);
    border: 1px solid rgba(8,145,178,0.25);
    border-radius: 999px;
    padding: 5px 14px;
    font-size: 0.76rem;
    color: #0891b2;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.pulse-dot {
    width: 7px; height: 7px;
    background: #0891b2;
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
    0%,100% { opacity:1; transform:scale(1); }
    50%      { opacity:0.3; transform:scale(0.7); }
}

/* ─ Sidebar section label ────────────────────────────────────────────────── */
.sb-label {
    font-size: 0.70rem;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.09em;
    font-weight: 600;
    margin: 20px 0 8px;
}

/* ─ Botón primario ───────────────────────────────────────────────────────── */
.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--r-md) !important;
    padding: 10px 18px !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 3px 12px rgba(37,99,235,0.28) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 7px 20px rgba(37,99,235,0.40) !important;
    background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

/* ─ Sidebar info card ────────────────────────────────────────────────────── */
.sb-card {
    background: #f8fafc;
    border: 1px solid rgba(0,0,0,0.07);
    border-radius: var(--r-md);
    padding: 14px 16px;
    margin-top: 14px;
}
.sb-card h4 {
    margin: 0 0 9px !important;
    font-size: 0.72rem !important;
    color: var(--text-2) !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
}
.sb-card p {
    margin: 0 !important;
    font-size: 0.84rem;
    color: var(--text-2);
    line-height: 1.85;
}

/* ─ Contador de mensajes ─────────────────────────────────────────────────── */
.sb-counter {
    font-size: 0.74rem;
    color: var(--text-3);
    text-align: center;
    margin: 10px 0 0;
    background: #f1f5f9;
    border-radius: 999px;
    padding: 4px 0;
}

/* ─ Header principal ─────────────────────────────────────────────────────── */
.main-hdr {
    display: flex;
    align-items: center;
    gap: 20px;
    padding: 28px 0 20px;
    margin-bottom: 6px;
    border-bottom: 1.5px solid #e2e8f0;
}
.main-hdr img.hdr-logo {
    height: 64px;
    width: auto;
    filter: drop-shadow(0 3px 10px var(--accent-glow));
}
.main-hdr h1 {
    margin: 0 !important;
    font-size: 1.85rem !important;
    font-weight: 800 !important;
    line-height: 1.1 !important;
    background: linear-gradient(100deg, #2563eb 10%, #0891b2 80%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.main-hdr p {
    margin: 5px 0 0 !important;
    font-size: 0.84rem;
    color: var(--text-2);
}

/* ─ Mensajes del chat ────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background: transparent !important;
    padding: 6px 2px !important;
    gap: 14px !important;
}

/* Avatar asistente */
[data-testid="stChatMessageAvatarAssistant"] {
    background: rgba(8,145,178,0.08) !important;
    border: 1.5px solid rgba(8,145,178,0.28) !important;
    border-radius: 50% !important;
}
/* Avatar usuario */
[data-testid="stChatMessageAvatarUser"] {
    background: rgba(37,99,235,0.07) !important;
    border: 1.5px solid rgba(37,99,235,0.22) !important;
    border-radius: 50% !important;
}

/* Contenido del mensaje asistente */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
  [data-testid="stMarkdownContainer"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-left: 3px solid #0891b2 !important;
    border-radius: 4px var(--r-lg) var(--r-lg) var(--r-lg) !important;
    padding: 14px 18px !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.07) !important;
    color: #0f172a !important;
    font-size: 0.93rem !important;
    line-height: 1.75 !important;
}

/* Contenido del mensaje usuario */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
  [data-testid="stMarkdownContainer"] {
    background: linear-gradient(135deg, #dbeafe 0%, #eff6ff 100%) !important;
    border: 1px solid #bfdbfe !important;
    border-radius: var(--r-lg) 4px var(--r-lg) var(--r-lg) !important;
    padding: 12px 18px !important;
    box-shadow: 0 2px 10px rgba(37,99,235,0.10) !important;
    color: #1e3a8a !important;
    font-size: 0.93rem !important;
    line-height: 1.65 !important;
}

/* Párrafos dentro de burbujas */
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
    margin-bottom: 0.45em !important;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p:last-child {
    margin-bottom: 0 !important;
}

/* ─ Input de chat ────────────────────────────────────────────────────────── */
/* Barra sticky del fondo */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottom"] > div > div {
    background: var(--bg-main) !important;
    box-shadow: none !important;
    border-top: 1px solid #e2e8f0 !important;
}
/* Todos los divs internos del input */
[data-testid="stChatInput"],
[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] > div > div,
[data-testid="stChatInput"] > div > div > div {
    background: #ffffff !important;
}
[data-testid="stChatInput"]  {
    border-radius: var(--r-lg) !important;
}   
[data-testid="stChatInput"] > div {
    border: 1.5px solid #cbd5e1 !important;
    border-radius: var(--r-lg) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05) !important;
}
[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.10) !important;
}
[data-testid="stChatInput"] textarea {
    color: var(--text-1) !important;
    background: #ffffff !important;
    font-size: 0.92rem !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: var(--text-3) !important;
}

/* ─ Spinner ──────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] > div {
    border-top-color: var(--teal) !important;
}

/* ─ Scrollbar ────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.12);
    border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.22); }
</style>
""", unsafe_allow_html=True)

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