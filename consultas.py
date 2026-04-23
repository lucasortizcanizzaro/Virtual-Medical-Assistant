import os
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from neo4j.exceptions import ServiceUnavailable, CypherSyntaxError
from google.genai.errors import ClientError, ServerError
from obtenerSintomas import MedicoDB

# En local carga el .env; en Streamlit Cloud no existe ese archivo
# y las credenciales se leen desde st.secrets (ver más abajo).
load_dotenv()

# Patrón que detecta operaciones de escritura en Cypher
_CYPHER_WRITE_PATTERN = re.compile(
    r'\b(create|delete|detach|merge|set|remove|drop|call)\b',
    re.IGNORECASE
)


def _es_query_segura(query: str) -> bool:
    """Bloquea operaciones de escritura en consultas generadas por la IA."""
    return not _CYPHER_WRITE_PATTERN.search(query)


def _generar_con_reintento(client, model: str, contents: str, config, max_intentos: int = 3) -> str:
    """Llama a generate_content con reintento exponencial ante errores 429 y 500."""
    espera = 5  # segundos iniciales de espera
    for intento in range(max_intentos):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            ).text
        except ServerError:
            # Error 500 del servidor de Gemini — suele ser transitorio
            if intento < max_intentos - 1:
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError("El servidor de Gemini no está disponible en este momento. Intenta de nuevo en unos segundos.")
        except ClientError as e:
            if e.code == 429 and intento < max_intentos - 1:
                time.sleep(espera)
                espera *= 2  # backoff exponencial: 5s, 10s, 20s
                continue
            elif e.code == 429:
                raise RuntimeError("Límite de solicitudes a la API de Gemini alcanzado. Espera unos segundos e intenta de nuevo.")
            elif e.code in (401, 403):
                raise RuntimeError("API key de Gemini inválida o sin permisos. Verifica tu configuración.")
            else:
                raise


def _get_secret(key: str) -> str:
    """Lee un secret desde st.secrets (Streamlit Cloud) o desde variables de entorno (local)."""
    try:
        import streamlit as st
        return st.secrets[key]
    except (ImportError, KeyError):
        return os.getenv(key, "")


class AsistenteMedico:
    def __init__(self):
        # Cliente único de la nueva SDK
        self.client = genai.Client(api_key=_get_secret("GEMINI_API_KEY"))

        # La conexión a Neo4j se configura desde secrets (Cloud) o .env (local)
        self.db = MedicoDB(
            uri=_get_secret("NEO4J_URI") or "bolt://localhost:7687",
            user=_get_secret("NEO4J_USERNAME") or "neo4j",
            password=_get_secret("NEO4J_PASSWORD"),
        )

        # Configuración del modelo 1: Traduce lenguaje natural → Cypher
        self.config_traductor = types.GenerateContentConfig(
            system_instruction="""Eres un experto en Neo4j. Traduces lenguaje natural a consultas Cypher.
Esquema de la base de datos:
- Nodos: Enfermedad {nombre, gravedad}, Sintoma {nombre, habitualidad}, Especialidad {nombre}
- Relaciones: (Enfermedad)-[:GENERA]->(Sintoma), (Especialidad)-[:TRATA]->(Enfermedad)

Reglas estrictas:
1. Devuelve SOLO el código Cypher. Sin explicaciones ni bloques de código markdown.
2. Usa toLower(n.nombre) CONTAINS toLower('valor') para búsquedas flexibles.
3. Si la pregunta no puede responderse con este esquema, devuelve exactamente: error
4. NUNCA generes operaciones de escritura (CREATE, DELETE, MERGE, SET, REMOVE, DROP). Solo consultas de lectura.""",
        )

        # Configuración del modelo 2: Convierte datos crudos en respuesta humana
        self.config_redactor = types.GenerateContentConfig(
            system_instruction="""Eres un asistente médico empático. Explica resultados de bases de datos
médicas de forma clara y amigable para pacientes no especializados.
Responde siempre en español y sugiere consultar a un médico para diagnósticos definitivos.""",
        )

    def preguntar(self, texto_usuario: str, historial: list = None) -> str:
        # Construir contexto conversacional para el modelo Cypher
        if historial and len(historial) > 1:
            mensajes_previos = historial[-7:-1]  # Últimos 6 mensajes, excluye el actual
            lineas = []
            for msg in mensajes_previos:
                rol = "Paciente" if msg["role"] == "user" else "Asistente"
                # Truncar cada mensaje para no inflar el contexto
                contenido = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
                lineas.append(f"{rol}: {contenido}")
            contexto = "Contexto previo de la conversación:\n" + "\n".join(lineas) + f"\n\nPregunta actual: {texto_usuario}"
        else:
            contexto = texto_usuario

        # Paso 1: IA traduce la pregunta del usuario a una consulta Cypher
        try:
            cypher_query = _generar_con_reintento(
                self.client, "gemini-2.5-flash", contexto, self.config_traductor
            ).strip()
        except Exception as e:
            return str(e)

        if cypher_query.lower() == "error":
            return (
                "Lo siento, mi base de datos solo contiene información sobre enfermedades, "
                "síntomas y especialidades médicas. ¿Puedes reformular tu pregunta?"
            )

        # DEBUG TEMPORAL: mostrar la query generada para verificar que sea correcta
        import streamlit as st
        st.caption(f"🔍 Query generada: `{cypher_query}`")

        # Validación de seguridad: bloquear operaciones de escritura
        if not _es_query_segura(cypher_query):
            return "Lo siento, no puedo procesar esa solicitud."

        # Paso 2: Ejecutar la consulta Cypher en Neo4j
        try:
            datos = self.db.ejecutar_consulta(cypher_query)
        except ServiceUnavailable:
            return "No se pudo conectar a la base de datos. Por favor intenta de nuevo más tarde."
        except CypherSyntaxError:
            return "Hubo un problema al interpretar tu consulta. Intenta describirla de otra forma."
        except Exception as e:
            return f"Ocurrió un error inesperado al consultar la base de datos: {e}"

        if not datos:
            return "No encontré información relacionada en mi base de datos. Intenta describir tus síntomas con más detalle."

        # Paso 3: IA convierte los datos crudos en una respuesta amigable
        prompt_redaccion = f"""
El usuario realizó esta consulta: "{texto_usuario}"
Los datos encontrados en la base de datos médica son: {datos}

Redacta una respuesta clara y amigable basada ÚNICAMENTE en esos datos.
"""
        try:
            return _generar_con_reintento(
                self.client, "gemini-2.5-flash", prompt_redaccion, self.config_redactor
            )
        except Exception as e:
            return str(e)

    def cerrar(self):
        self.db.close()


