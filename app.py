import streamlit as st
from consultas import AsistenteMedico

# 1. Configuración de la página
st.set_page_config(page_title="Asistente Médico", layout="wide")
st.title("🩺 Sistema de Orientación Médica Inteligente")


# 2. Inicializar el asistente una sola vez (cacheado por Streamlit)
@st.cache_resource
def crear_asistente():
    return AsistenteMedico()


asistente = crear_asistente()

# 3. Inicializar historial de mensajes
if "mensajes" not in st.session_state:
    st.session_state.mensajes = [
        {"role": "assistant", "content": "¡Hola! Soy tu asistente basado en evidencia médica. ¿Qué síntomas experimentas?"}
    ]

# 4. Menú lateral
with st.sidebar:
    st.header("Historial de Consultas")
    if st.button("➕ Crear nuevo chat"):
        st.session_state.mensajes = [
            {"role": "assistant", "content": "¡Hola! Chat reiniciado. ¿En qué puedo ayudarte?"}
        ]
        st.rerun()
    st.write("Aquí se verán tus chats guardados (Próximamente)")

# 5. Mostrar los mensajes guardados
for msj in st.session_state.mensajes:
    with st.chat_message(msj["role"]):
        st.write(msj["content"])

# 6. Input del usuario y procesamiento
if prompt := st.chat_input("Describe tus síntomas aquí..."):
    # Guardar y mostrar el mensaje del usuario
    st.session_state.mensajes.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # Llamar al asistente y mostrar la respuesta
    with st.chat_message("assistant"):
        with st.spinner("Analizando tu consulta..."):
            respuesta = asistente.preguntar(prompt)
        st.write(respuesta)
        st.session_state.mensajes.append({"role": "assistant", "content": respuesta})