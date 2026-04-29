import os
import re
import time
import unicodedata
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


def _sin_tildes(texto: str) -> str:
    """Elimina tildes y diacríticos. Ej: 'diarréa' → 'diarrea'."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


def _es_query_segura(query: str) -> bool:
    """Bloquea operaciones de escritura en consultas generadas por la IA."""
    return not _CYPHER_WRITE_PATTERN.search(query)


def _generar_embedding(client, texto: str) -> list:
    """Convierte texto en un vector de 768 dimensiones usando text-embedding-004."""
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=texto,
    )
    return result.embeddings[0].values


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

        # Macro de normalización reutilizable en el system_instruction
        _norm = lambda campo: (
            f"replace(replace(replace(replace(replace(replace(replace("
            f"toLower({campo}),'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u'),'ñ','n'),'ü','u')"
        )

        # Configuración del modelo 1: Traduce lenguaje natural → Cypher
        self.config_traductor = types.GenerateContentConfig(
            system_instruction=f"""Eres un experto en Neo4j. Traduces lenguaje natural a consultas Cypher.
Esquema de la base de datos:
- Nodos: Enfermedad {{nombre, gravedad}}, Sintoma {{nombre, habitualidad}}, Especialidad {{nombre}}
- Relaciones: (Enfermedad)-[:GENERA]->(Sintoma), (Especialidad)-[:TRATA]->(Enfermedad)

Reglas estrictas:
1. Devuelve SOLO el código Cypher. Sin explicaciones ni bloques de código markdown.
2. Para comparaciones de texto SIEMPRE normaliza ambos lados quitando tildes y usando minúsculas:
   {_norm("n.nombre")} CONTAINS {_norm("'valor'")}
3. Si la pregunta no puede responderse con este esquema, devuelve exactamente: error
4. NUNCA generes operaciones de escritura (CREATE, DELETE, MERGE, SET, REMOVE, DROP). Solo consultas de lectura.""",
        )

        # Configuración del modelo 2: Evalúa qué enfermedad se adecúa mejor al paciente
        self.config_evaluador = types.GenerateContentConfig(
            system_instruction="""Eres un evaluador médico. Recibes la consulta de un paciente y datos de enfermedades de una base de datos.

Tu tarea es determinar qué enfermedad se adecúa mejor a lo que describe el paciente.

Reglas estrictas:
1. Si los datos apuntan claramente a UNA enfermedad (o el contexto permite elegir), responde exactamente:
   DECISION: <nombre exacto de la enfermedad tal como aparece en los datos>

2. Si hay VARIAS enfermedades posibles y no hay suficiente información para decidir, responde exactamente:
   PREGUNTA: <una pregunta corta y específica que pida UN síntoma clave que permita diferenciarlas>

3. Orden de preferencia de gravedad cuando el paciente no la especifica: leve > moderada > grave > crítica.
   En caso de duda, siempre muestra la menos grave.

4. Devuelve ÚNICAMENTE el prefijo y el contenido. Sin texto adicional.""",
        )

        # Configuración del modelo 3: Convierte datos crudos en respuesta humana
        self.config_redactor = types.GenerateContentConfig(
            system_instruction="""Eres un asistente médico empático. Explica resultados de bases de datos
médicas de forma clara y amigable para pacientes no especializados.
Responde siempre en español y sugiere consultar a un médico para diagnósticos definitivos.""",
        )

    def preguntar(self, texto_usuario: str, historial: list = None) -> str:
        # Normalizar input del usuario: quitar tildes para asegurar el match
        texto_normalizado = _sin_tildes(texto_usuario)

        # Construir contexto conversacional para el modelo Cypher
        if historial and len(historial) > 1:
            mensajes_previos = historial[-7:-1]  # Últimos 6 mensajes, excluye el actual
            lineas = []
            for msg in mensajes_previos:
                rol = "Paciente" if msg["role"] == "user" else "Asistente"
                # Truncar cada mensaje para no inflar el contexto
                contenido = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
                lineas.append(f"{rol}: {_sin_tildes(contenido)}")
            contexto = "Contexto previo de la conversacion:\n" + "\n".join(lineas) + f"\n\nPregunta actual: {texto_normalizado}"
        else:
            contexto = texto_normalizado

        # --- RUTA 1: Búsqueda semántica por vector ---
        # Genera el embedding del texto del usuario y busca síntomas similares en Neo4j.
        # Si la similitud es suficientemente alta (≥0.75), usa estos resultados directamente.
        datos = []
        try:
            vector = _generar_embedding(self.client, texto_usuario)
            candidatos = self.db.buscar_por_vector("sintoma_embeddings", vector, top_k=5)
            # Filtrar solo resultados con alta similitud semántica
            datos = [d for d in candidatos if d.get("relevancia", 0) >= 0.75]
        except Exception:
            datos = []  # Si falla el embedding, continúa con Text-to-Cypher

        # --- RUTA 2: Text-to-Cypher (fallback si el vector no dio resultados) ---
        if not datos:
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

            if not _es_query_segura(cypher_query):
                return "Lo siento, no puedo procesar esa solicitud."

            try:
                datos = self.db.ejecutar_consulta(cypher_query)
            except ServiceUnavailable:
                return "No se pudo conectar a la base de datos. Por favor intenta de nuevo más tarde."
            except CypherSyntaxError as e:
                return f"Error de sintaxis en la query generada.\n\nQuery: `{cypher_query}`\n\nError: {e}"
            except Exception as e:
                return f"Ocurrió un error inesperado al consultar la base de datos: {e}"

            if not datos:
                return f"Sin resultados. Query ejecutada:\n```\n{cypher_query}\n```"

        # Paso 3: Evaluar qué enfermedad se adecúa mejor al paciente
        prompt_evaluacion = f"""
Consulta del paciente: "{texto_usuario}"
Datos encontrados en la base de datos: {datos}
"""
        try:
            evaluacion = _generar_con_reintento(
                self.client, "gemini-2.5-flash", prompt_evaluacion, self.config_evaluador
            ).strip()
        except Exception as e:
            return str(e)

        # Si el evaluador pide más info, devolver la pregunta directamente al usuario
        if evaluacion.startswith("PREGUNTA:"):
            return evaluacion[len("PREGUNTA:"):].strip()

        # Si tomó una decisión, filtrar los datos a esa enfermedad
        if evaluacion.startswith("DECISION:"):
            nombre_seleccionado = evaluacion[len("DECISION:"):].strip()
            datos_filtrados = [d for d in datos if nombre_seleccionado.lower() in str(d).lower()]
            datos_para_redactor = datos_filtrados if datos_filtrados else datos
        else:
            datos_para_redactor = datos

        # Paso 4: IA convierte los datos seleccionados en una respuesta amigable
        prompt_redaccion = f"""
El usuario realizó esta consulta: "{texto_usuario}"
Los datos encontrados en la base de datos médica son: {datos_para_redactor}

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


