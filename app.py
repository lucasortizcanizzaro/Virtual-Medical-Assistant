import streamlit as st
from consultas import AsistenteMedico

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
    --bg-main:     #0d1117;
    --bg-sidebar:  #0f1623;
    --bg-card:     #161d2d;
    --bg-input:    #1a2236;
    --accent:      #3b82f6;
    --accent-dim:  rgba(59,130,246,0.15);
    --accent-glow: rgba(59,130,246,0.35);
    --teal:        #2dd4bf;
    --teal-dim:    rgba(45,212,191,0.12);
    --teal-glow:   rgba(45,212,191,0.30);
    --danger:      #f87171;
    --text-1:      #e2e8f0;
    --text-2:      #94a3b8;
    --text-3:      #4b5563;
    --border:      rgba(255,255,255,0.07);
    --border-acc:  rgba(59,130,246,0.30);
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
}
[data-testid="stSidebar"] * { color: var(--text-1) !important; }

/* ─ Sidebar: logo ────────────────────────────────────────────────────────── */
.sb-logo {
    text-align: center;
    padding: 28px 0 20px;
}
.sb-logo .icon {
    font-size: 3.2rem;
    display: block;
    filter: drop-shadow(0 0 14px var(--teal-glow));
}
.sb-logo .brand {
    display: block;
    margin-top: 10px;
    font-size: 1.3rem;
    font-weight: 800;
    letter-spacing: -0.3px;
    background: linear-gradient(100deg, #60a5fa 20%, #2dd4bf 80%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.sb-logo .tagline {
    display: block;
    margin-top: 4px;
    font-size: 0.73rem;
    color: var(--text-3);
    letter-spacing: 0.04em;
}
.sb-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 0 0 18px;
}

/* ─ Status badge ─────────────────────────────────────────────────────────── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: var(--teal-dim);
    border: 1px solid rgba(45,212,191,0.30);
    border-radius: 999px;
    padding: 5px 13px;
    font-size: 0.76rem;
    color: var(--teal);
    font-weight: 600;
    letter-spacing: 0.02em;
}
.pulse-dot {
    width: 7px; height: 7px;
    background: var(--teal);
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
    0%,100% { opacity:1; transform:scale(1); }
    50%      { opacity:0.3; transform:scale(0.7); }
}

/* ─ Sidebar section label ────────────────────────────────────────────────── */
.sb-label {
    font-size: 0.72rem;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 20px 0 8px;
}

/* ─ Botón primario ───────────────────────────────────────────────────────── */
.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
    color: #fff !important;
    border: 1px solid rgba(96,165,250,0.25) !important;
    border-radius: var(--r-md) !important;
    padding: 10px 18px !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.35) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 22px rgba(37,99,235,0.50) !important;
    background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

/* ─ Sidebar info card ────────────────────────────────────────────────────── */
.sb-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 14px 16px;
    margin-top: 14px;
}
.sb-card h4 {
    margin: 0 0 9px !important;
    font-size: 0.76rem !important;
    color: var(--text-2) !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.sb-card p {
    margin: 0 !important;
    font-size: 0.85rem;
    color: var(--text-1);
    line-height: 1.85;
}

/* ─ Contador de mensajes ─────────────────────────────────────────────────── */
.sb-counter {
    font-size: 0.75rem;
    color: var(--text-3);
    text-align: center;
    margin: 10px 0 0;
}

/* ─ Header principal ─────────────────────────────────────────────────────── */
.main-hdr {
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 32px 0 18px;
    margin-bottom: 4px;
    border-bottom: 1px solid var(--border);
}
.main-hdr .hdr-icon {
    font-size: 2.8rem;
    filter: drop-shadow(0 0 12px var(--teal-glow));
}
.main-hdr h1 {
    margin: 0 !important;
    font-size: 1.85rem !important;
    font-weight: 800 !important;
    line-height: 1.1 !important;
    background: linear-gradient(100deg, #60a5fa 10%, #2dd4bf 80%);
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
    padding: 6px 2px !important;
    gap: 14px !important;
}

/* Avatar asistente */
[data-testid="stChatMessageAvatarAssistant"] {
    background: var(--teal-dim) !important;
    border: 1.5px solid rgba(45,212,191,0.40) !important;
    border-radius: 50% !important;
}
/* Avatar usuario */
[data-testid="stChatMessageAvatarUser"] {
    background: var(--accent-dim) !important;
    border: 1.5px solid var(--border-acc) !important;
    border-radius: 50% !important;
}

/* Contenido del mensaje asistente */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])
  [data-testid="stMarkdownContainer"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-left: 3px solid var(--teal) !important;
    border-radius: 4px var(--r-lg) var(--r-lg) var(--r-lg) !important;
    padding: 14px 18px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.40) !important;
    color: var(--text-1) !important;
    font-size: 0.93rem !important;
    line-height: 1.75 !important;
}

/* Contenido del mensaje usuario */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
  [data-testid="stMarkdownContainer"] {
    background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%) !important;
    border: 1px solid rgba(96,165,250,0.20) !important;
    border-radius: var(--r-lg) 4px var(--r-lg) var(--r-lg) !important;
    padding: 12px 18px !important;
    box-shadow: 0 4px 20px rgba(29,78,216,0.30) !important;
    color: #e0eaff !important;
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
[data-testid="stChatInput"] > div {
    background: var(--bg-input) !important;
    border: 1.5px solid var(--border-acc) !important;
    border-radius: var(--r-lg) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-dim) !important;
}
[data-testid="stChatInput"] textarea {
    color: var(--text-1) !important;
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
    background: rgba(255,255,255,0.09);
    border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.18); }
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
with st.sidebar:
    st.markdown("""
    <div class="sb-logo">
        <span class="icon">🩺</span>
        <span class="brand">MediAI</span>
        <span class="tagline">Asistente de Orientación Médica</span>
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
    <div class="sb-card" style="margin-top:28px; border-left:3px solid #f87171;">
        <h4>⚠️ Aviso</h4>
        <p>Este asistente provee orientación general y no reemplaza el diagnóstico de un médico certificado.</p>
    </div>
    <div class="sb-card">
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
st.markdown("""
<div class="main-hdr">
    <span class="hdr-icon">🩺</span>
    <div>
        <h1>MediAI</h1>
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