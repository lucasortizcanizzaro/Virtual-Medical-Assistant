import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from obtenerSintomas import MedicoDB

# En local carga el .env; en Streamlit Cloud no existe ese archivo
# y las credenciales se leen desde st.secrets (ver más abajo).
load_dotenv()


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
3. Si la pregunta no puede responderse con este esquema, devuelve exactamente: error""",
        )

        # Configuración del modelo 2: Convierte datos crudos en respuesta humana
        self.config_redactor = types.GenerateContentConfig(
            system_instruction="""Eres un asistente médico empático. Explica resultados de bases de datos
médicas de forma clara y amigable para pacientes no especializados.
Responde siempre en español y sugiere consultar a un médico para diagnósticos definitivos.""",
        )

    def preguntar(self, texto_usuario: str) -> str:
        # Paso 1: IA traduce la pregunta del usuario a una consulta Cypher
        cypher_query = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=texto_usuario,
            config=self.config_traductor,
        ).text.strip()

        if cypher_query.lower() == "error":
            return (
                "Lo siento, mi base de datos solo contiene información sobre enfermedades, "
                "síntomas y especialidades médicas. ¿Puedes reformular tu pregunta?"
            )

        # Paso 2: Ejecutar la consulta Cypher en Neo4j
        try:
            datos = self.db.ejecutar_consulta(cypher_query)
        except Exception:
            return "Ocurrió un error al consultar la base de datos. Por favor intenta de nuevo."

        if not datos:
            return "No encontré información relacionada en mi base de datos. Intenta describir tus síntomas con más detalle."

        # Paso 3: IA convierte los datos crudos en una respuesta amigable
        prompt_redaccion = f"""
El usuario realizó esta consulta: "{texto_usuario}"
Los datos encontrados en la base de datos médica son: {datos}

Redacta una respuesta clara y amigable basada ÚNICAMENTE en esos datos.
"""
        return self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_redaccion,
            config=self.config_redactor,
        ).text

    def cerrar(self):
        self.db.close()


