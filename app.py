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

def _inject_sidebar_toggle() -> None:
    """Inject a real floating button that triggers Streamlit's native sidebar toggle."""
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        (function() {
            function injectBtn() {
                if (window.parent.document.getElementById('_sb_toggle_btn')) return;

                var btn = document.createElement('button');
                btn.id = '_sb_toggle_btn';
                btn.innerHTML = '&#9776;';
                btn.title = 'Abrir / cerrar panel';
                btn.style.cssText = [
                    'position:fixed',
                    'left:0',
                    'top:50%',
                    'transform:translateY(-50%)',
                    'z-index:99999',
                    'width:28px',
                    'height:54px',
                    'border:none',
                    'border-radius:0 10px 10px 0',
                    'background:linear-gradient(180deg,#2563eb,#0891b2)',
                    'color:#fff',
                    'font-size:18px',
                    'cursor:pointer',
                    'box-shadow:3px 0 14px rgba(37,99,235,0.45)',
                    'transition:width 0.18s ease',
                    'display:flex',
                    'align-items:center',
                    'justify-content:center',
                    'padding:0',
                ].join(';');

                btn.addEventListener('mouseenter', function(){ btn.style.width='36px'; });
                btn.addEventListener('mouseleave', function(){ btn.style.width='28px'; });

                btn.addEventListener('click', function() {
                    try {
                        var el = window.parent.document.querySelector('[data-testid="stExpandSidebarButton"]');
                        if (el) el.click();
                    } catch(e) {
                        console.warn('Sidebar toggle error:', e);
                    }
                });

                var target = window.parent ? window.parent.document.body : document.body;
                target.appendChild(btn);
            }

            injectBtn();
            setTimeout(injectBtn, 600);
            setTimeout(injectBtn, 1800);
        })();
        </script>
        """,
        height=0,
    )

# ── Configuración de la página ────────────────────────────────────────────────
st.set_page_config(
    page_title="MEDIC-AI · Asistente Médico",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personalizado ────────────────────────────────────────────────────────
_load_css()
_inject_sidebar_toggle()

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