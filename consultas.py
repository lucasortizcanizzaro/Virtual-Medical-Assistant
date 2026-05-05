import logging
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

# Buffer de timing: se limpia al inicio de cada llamada a preguntar()
_timing_log: list[str] = []

def _log(msg, *args):
    import datetime
    text = (msg % args) if args else msg
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    _timing_log.append(f"{ts}  {text}")

# Modelo LLM utilizado en todos los agentes
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

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


EMBEDDING_MODEL = "gemini-embedding-2"


def _generar_embedding(api_key: str, texto: str) -> list:
    """Convierte texto en un vector de 768 dimensiones via REST (gemini-embedding-2)."""
    import requests
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent",
        params={"key": api_key},
        json={
            "model": f"models/{EMBEDDING_MODEL}",
            "content": {"parts": [{"text": texto}]},
            "taskType": "RETRIEVAL_QUERY",
            "outputDimensionality": 768,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]["values"]


def verificar_api(api_key: str) -> bool:
    """Hace una llamada mínima para comprobar si la API de Gemini responde."""
    import requests
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent",
            params={"key": api_key},
            json={
                "model": f"models/{EMBEDDING_MODEL}",
                "content": {"parts": [{"text": "ping"}]},
                "taskType": "RETRIEVAL_QUERY",
                "outputDimensionality": 1,
            },
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _generar_embeddings_sintomas(api_key: str, sintomas_json: list) -> list:
    """Añade el vector embedding a cada síntoma extraído para la búsqueda unificada."""
    return [
        {"nombre": item["nombre"], "intensidad": item["intensidad"], "vector": _generar_embedding(api_key, item["nombre"])}
        for item in sintomas_json
    ]


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


def _seleccionar_sintoma_fallback(sintomas_por_enf: dict, ya_vistos: set) -> str:
    """Elige el síntoma con mayor poder diferenciador (ni en todas ni en ninguna candidata)."""
    conteo: dict[str, int] = {}
    for syms in sintomas_por_enf.values():
        for s in syms:
            key = s.lower()
            if key not in ya_vistos:
                conteo[s] = conteo.get(s, 0) + 1
    if not conteo:
        return "algún síntoma adicional"
    total = len(sintomas_por_enf)
    # El mejor diferenciador está en ~mitad de las enfermedades
    mejor = min(conteo.items(), key=lambda x: abs(x[1] - total / 2))
    return mejor[0]


def _get_secret(key: str) -> str:
    """Lee un secret desde st.secrets (Streamlit Cloud) o desde variables de entorno (local)."""
    try:
        import streamlit as st
        return st.secrets[key]
    except (ImportError, KeyError):
        return os.getenv(key, "")


class AsistenteMedico:
    def __init__(self):
        api_key = _get_secret("GEMINI_API_KEY")
        self._api_key = api_key
        # Cliente nuevo SDK — para modelos de generación
        self.client = genai.Client(api_key=api_key)

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
4. NUNCA generes operaciones de escritura (CREATE, DELETE, MERGE, SET, REMOVE, DROP). Solo consultas de lectura.

Contexto del flujo:
- Un agente evaluador analiza los datos que devuelves para determinar qué enfermedad corresponde al paciente.
- Si el evaluador no tiene suficiente información para decidir, le hace UNA pregunta al paciente pidiendo un síntoma adicional.
- Cuando el paciente responde esa pregunta, el historial lo incluye. En ese caso, combiná TODOS los síntomas mencionados en la conversación para generar una query más específica que ayude al evaluador a tomar la decisión.""",
        )

        # Config combinado: evalúa candidatas Y redacta toda la respuesta en una sola llamada
        self.config_evaluador_redactor = types.GenerateContentConfig(
            system_instruction="""Eres evaluador médico y redactor para un asistente médico virtual.
Responde SIEMPRE en el idioma indicado en el prompt ("es"=español, "en"=inglés).
Recibes la consulta del paciente, síntomas descartados, síntomas ya conocidos y datos de enfermedades con todos sus síntomas.

CASO A — Ganador claro (score muy superior, síntomas inequívocos, o síntomas descartados eliminan las demás):
  Redactá directamente una respuesta empática: nombrá la condición probable, su gravedad,
  síntomas que la sustentan, especialidad/es recomendadas y recordale consultar a un médico. Sin prefijo.

CASO B — Varias enfermedades compiten (scores similares, síntomas compartidos, cuadro ambiguo):
  1. Elegí el síntoma con MAYOR poder diferenciador: presente en ALGUNAS candidatas pero AUSENTE
     en otras, NO en la lista de ya_conocidos, fácil de identificar por el paciente.
  2. Primera línea obligatoria:
     DIFERENCIAL_SINTOMA: <nombre exacto del síntoma elegido>
  3. A continuación, la respuesta empática: reconocé los síntomas del paciente, listá las
     condiciones posibles con su gravedad, y preguntá directamente si tiene el síntoma elegido.

Preferencia de gravedad: leve > moderada > grave > crítica.
Usá los síntomas descartados para eliminar candidatas.""",
        )

        # Config unificado: clasifica intención, detecta idioma Y extrae síntomas en una sola llamada
        self.config_analizador = types.GenerateContentConfig(
            system_instruction="""Analizas mensajes de un asistente médico. Tres tareas:
1) Intención: SALUDO|FUNCIONALIDAD|SALUDO_FUNC|CONSULTA
   SALUDO=solo saludo/expresión social. FUNCIONALIDAD=pregunta sobre qué puede hacer el asistente.
   SALUDO_FUNC=ambas. CONSULTA=síntomas/enfermedades/medicamentos. Mezcla con consulta médica→CONSULTA.
2) Idioma del mensaje: "es" si está en español, "en" si está en inglés.
3) Síntomas con intensidad (solo si CONSULTA). Normaliza SIEMPRE los nombres al español médico:
   'a little','mild','barely'/'un poco','leve','apenas'→0.7 | sin adjetivos→1.0 | 'a lot','very','strong'/'mucho','muy','fuerte'→1.35
Devuelve SOLO JSON sin markdown:
{"intencion":"CONSULTA","idioma":"es","sintomas":[{"nombre":"nombre en español","intensidad":1.0}]}
Si no es CONSULTA, "sintomas":[].""",
            temperature=0.0,
            max_output_tokens=150,
        )

        # Configuración del modelo 0b: Responde saludos y preguntas de funcionalidad
        self.config_conversacional = types.GenerateContentConfig(
            system_instruction="""Eres MEDIC-AI, un asistente de orientación médica con inteligencia artificial.
Responde en el mismo idioma que usa el usuario en su mensaje, de forma cálida y concisa.

Si el usuario saluda → devuelve un saludo cordial y preséntate brevemente.
Si pregunta por tu funcionalidad → explica que podés relacionar síntomas con posibles enfermedades,
  sugerir la especialidad médica adecuada y orientar sobre nivel de gravedad, siempre recordando que
  no reemplazás a un médico certificado.
Si hace ambas cosas → saluda y explica tu funcionalidad en el mismo mensaje.
No incluyas diagnósticos ni información médica específica en esta respuesta.""",
        )



    # Palabras clave médicas: si alguna aparece, la consulta no es un saludo puro
    _KW_MEDICOS = re.compile(
        r'\b(dolor|duele|tengo|siento|fiebre|tos|nausea|nauseas|vomito|vomitos|'
        r'mareo|mareos|cansancio|fatiga|sangre|sangrado|picazon|picazón|'
        r'ardor|inflamacion|inflamación|hinchazón|hinchazón|diarrea|estreñimiento|'
        r'cabeza|garganta|pecho|abdomen|espalda|pierna|brazo|ojo|oido|'
        r'sintoma|síntoma|enfermedad|diagnostico|diagnóstico|medicamento|'
        r'alergia|gripe|resfrio|resfrío|infeccion|infección|rash|sarpullido)\b',
        re.IGNORECASE,
    )
    _SALUDOS = re.compile(
        r'^\s*(hola|buenos?\s+d[ií]as?|buenas?\s+tardes?|buenas?\s+noches?|'
        r'hi|hey|saludos?|gracias|muchas\s+gracias|thank\s+you|thanks|'
        r'adios|adi[oó]s|hasta\s+luego|chau|bye|ok|okay|dale|perfecto|'
        r'entendido|de\s+nada|por\s+favor)[!?.,\s]*$',
        re.IGNORECASE,
    )
    # Subconjunto de saludos que son exclusivamente en inglés
    _SALUDOS_EN = re.compile(
        r'^\s*(hi|hey|thank\s+you|thanks|bye|ok|okay)[!?.,\s]*$',
        re.IGNORECASE,
    )

    def preguntar(self, texto_usuario: str, historial: list = None,
                  contexto_diferencial: dict = None) -> tuple:
        """Procesa la consulta del usuario.
        Retorna (respuesta: str, nuevo_contexto_diferencial: dict | None).
        nuevo_contexto_diferencial es None cuando no hay diagnóstico diferencial activo.
        """
        import json as _json

        _timing_log.clear()
        t_inicio = time.time()

        # ── Ruta ultra-rápida: saludo sin palabras médicas → 0 llamadas LLM ──
        # Nunca aplicar si hay un diferencial activo: la respuesta del usuario
        # ("no", "sí", etc.) debe llegar al Paso 2 para resolver la pregunta de descarte.
        texto_strip = texto_usuario.strip()
        if (
            not contexto_diferencial
            and self._SALUDOS.match(texto_strip)
            and not self._KW_MEDICOS.search(texto_strip)
        ):
            _log("[preguntar] saludo detectado por regex: %.3fs | TOTAL: %.3fs (0 LLM calls)",
                 time.time() - t_inicio, time.time() - t_inicio)
            _en = bool(self._SALUDOS_EN.match(texto_strip))
            return (
                "Hello! I'm **MEDIC-AI**, your AI medical guidance assistant. "
                "Describe your symptoms and I'll help identify possible causes, "
                "the recommended medical specialty, and severity level. "
                "Remember I'm not a substitute for a certified doctor. How can I help you?"
                if _en else
                "¡Hola! Soy **MEDIC-AI**, tu asistente de orientación médica. "
                "Podés describirme tus síntomas y te ayudaré a identificar posibles causas, "
                "la especialidad médica recomendada y el nivel de gravedad. "
                "Recordá que no reemplazo a un médico certificado. ¿En qué te puedo ayudar?",
                None,
            )

        # ── Paso 0+1: Clasificar intención y extraer síntomas (llamada unificada) ──
        intencion = "CONSULTA"
        idioma = "es"  # default; se actualiza con la respuesta del analizador
        sintomas_nuevos = []
        try:
            analisis_str = _generar_con_reintento(
                self.client, GEMINI_MODEL, texto_usuario, self.config_analizador
            ).strip()
            analisis = _json.loads(analisis_str)
            intencion = str(analisis.get("intencion", "CONSULTA")).strip().upper()
            idioma = str(analisis.get("idioma", "es")).strip().lower()
            if idioma not in ("es", "en"):
                idioma = "es"
            candidatos = analisis.get("sintomas", [])
            if isinstance(candidatos, list) and all(
                isinstance(item, dict) and "nombre" in item and "intensidad" in item
                for item in candidatos
            ):
                sintomas_nuevos = candidatos
        except Exception:
            intencion = "CONSULTA"
        _log("[preguntar] Paso 1 analizador: %.2fs | intencion=%s | sintomas=%s",
                    time.time() - t_inicio, intencion, [s["nombre"] for s in sintomas_nuevos])

        if intencion in ("SALUDO", "FUNCIONALIDAD", "SALUDO_FUNC") and not contexto_diferencial:
            try:
                t0 = time.time()
                resp = _generar_con_reintento(
                    self.client, GEMINI_MODEL, texto_usuario, self.config_conversacional
                )
                _log("[preguntar] conversacional: %.2fs | TOTAL: %.2fs",
                            time.time() - t0, time.time() - t_inicio)
                return resp, None
            except Exception as e:
                return str(e), None

        # ── Flujo médico ─────────────────────────────────────────────────────
        texto_normalizado = _sin_tildes(texto_usuario)

        # Contexto conversacional para el fallback Text-to-Cypher
        if historial and len(historial) > 1:
            mensajes_previos = historial[-7:-1]
            lineas = []
            for msg in mensajes_previos:
                rol = "Paciente" if msg["role"] == "user" else "Asistente"
                contenido = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
                lineas.append(f"{rol}: {_sin_tildes(contenido)}")
            contexto = "Contexto previo de la conversacion:\n" + "\n".join(lineas) + f"\n\nPregunta actual: {texto_normalizado}"
        else:
            contexto = texto_normalizado

        # ── Paso 2: Resolver y actualizar contexto diferencial previo ─────────
        sintomas_confirmados = list((contexto_diferencial or {}).get("sintomas_confirmados", []))
        sintomas_negados     = list((contexto_diferencial or {}).get("sintomas_negados", []))
        sintomas_acumulados  = list((contexto_diferencial or {}).get("sintomas_acumulados", []))

        if contexto_diferencial and "sintoma_preguntado" in contexto_diferencial:
            sintoma_preguntado = contexto_diferencial["sintoma_preguntado"]
            resp_lower = f" {texto_usuario.lower()} "

            _palabras_si = {
                "si", "sí", "yes", "tengo", "siento", "me duele", "noto",
                "también", "tambien", "claro", "correcto", "exacto",
                "efectivamente", "presenta", "suelo", "a veces",
            }
            _palabras_no = {
                "no", "tampoco", "nunca", "jamas", "jamás",
                "negativo", "ausente", "para nada",
            }

            confirmo = any(f" {p} " in resp_lower for p in _palabras_si)
            nego     = (
                any(f" {p} " in resp_lower for p in _palabras_no)
                or texto_usuario.strip().lower() == "no"
            )

            if confirmo and not nego:
                if sintoma_preguntado not in sintomas_confirmados:
                    sintomas_confirmados.append(sintoma_preguntado)
            elif nego:
                if sintoma_preguntado not in sintomas_negados:
                    sintomas_negados.append(sintoma_preguntado)

        # Acumular: síntomas previos + nuevos del input + confirmados por el usuario
        # Filtrar por seguridad: solo dicts con "nombre" e "intensidad"
        sintomas_acumulados = [
            s for s in sintomas_acumulados
            if isinstance(s, dict) and "nombre" in s and "intensidad" in s
        ]
        nombres_acumulados = {s["nombre"].lower() for s in sintomas_acumulados}

        for s in sintomas_nuevos:
            if s["nombre"].lower() not in nombres_acumulados:
                sintomas_acumulados.append(s)
                nombres_acumulados.add(s["nombre"].lower())

        for nombre in sintomas_confirmados:
            if nombre.lower() not in nombres_acumulados:
                sintomas_acumulados.append({"nombre": nombre, "intensidad": 1.0})
                nombres_acumulados.add(nombre.lower())

        # ── Paso 3: Búsqueda vectorial con todos los síntomas acumulados ──────
        datos = []
        if sintomas_acumulados:
            t0 = time.time()
            try:
                sintomas_con_vector = _generar_embeddings_sintomas(self._api_key, sintomas_acumulados)
                t_embed = time.time() - t0
                datos = self.db.buscar_con_intensidad_vectorial(sintomas_con_vector)
                _log("[preguntar] Paso 3 vectorial: embed=%.2fs neo4j=%.2fs resultados=%d", t_embed, time.time() - t0 - t_embed, len(datos))
            except Exception as e:
                _log("[preguntar] Paso 3 vectorial ERROR: %s", e)
                datos = []

        # --- Ruta 2: Fallback por nombre exacto si vector no dio resultados ---
        if not datos and sintomas_acumulados:
            t0 = time.time()
            try:
                datos = self.db.obtener_ranking_enfermedades(
                    [s["nombre"] for s in sintomas_acumulados]
                )
                _log("[preguntar] Ruta 2 nombre exacto: %.2fs resultados=%d", time.time() - t0, len(datos))
            except Exception as e:
                _log("[preguntar] Ruta 2 ERROR: %s", e)
                datos = []

        # --- Ruta 3: Text-to-Cypher para preguntas sin síntomas (informativas) ---
        if not datos and not sintomas_acumulados:
            t0 = time.time()
            try:
                cypher_query = _generar_con_reintento(
                    self.client, GEMINI_MODEL, contexto, self.config_traductor
                ).strip()
                _log("[preguntar] Ruta 3 traductor: %.2fs", time.time() - t0)
            except Exception as e:
                return str(e), None

            if cypher_query.lower() == "error":
                return (
                    "I'm sorry, my database only contains information about diseases, symptoms, "
                    "and medical specialties. Can you rephrase your question?"
                    if idioma == "en" else
                    "Lo siento, mi base de datos solo contiene información sobre enfermedades, "
                    "síntomas y especialidades médicas. ¿Puedes reformular tu pregunta?"
                ), None

            if not _es_query_segura(cypher_query):
                return (
                    "I'm sorry, I can't process that request."
                    if idioma == "en" else
                    "Lo siento, no puedo procesar esa solicitud."
                ), None

            try:
                datos = self.db.ejecutar_consulta(cypher_query)
            except ServiceUnavailable:
                return (
                    "Could not connect to the database. Please try again later."
                    if idioma == "en" else
                    "No se pudo conectar a la base de datos. Por favor intenta de nuevo más tarde."
                ), None
            except (CypherSyntaxError, Exception):
                datos = []

        # Normalizar datos: asegurar que todos los registros tengan la clave "enfermedad"
        datos = [d for d in datos if isinstance(d, dict) and d.get("enfermedad")]

        if not datos:
            return (
                "I couldn't find conditions matching the described symptoms. "
                "Can you provide more details or mention other symptoms?"
                if idioma == "en" else
                "No encontré condiciones que coincidan con los síntomas descritos. "
                "¿Puedes dar más detalles o mencionar otros síntomas?"
            ), None

        # ── Paso 4: Evaluar y redactar — 1 sola llamada LLM ───────────────────────
        # Obtener todos los síntomas por enfermedad desde Neo4j (rápido, sin costo de API)
        try:
            sintomas_por_enf = self.db.obtener_sintomas_enfermedades(
                [d["enfermedad"] for d in datos]
            )
        except Exception:
            sintomas_por_enf = {}

        ya_vistos = nombres_acumulados | {s.lower() for s in sintomas_negados}

        datos_con_sintomas = [
            {**d, "todos_sintomas": sintomas_por_enf.get(d["enfermedad"], d.get("sintomas", []))}
            for d in datos
        ]

        prompt_evaluacion = f"""
Idioma de respuesta: {"english" if idioma == "en" else "español"}
Consulta del paciente: "{texto_usuario}"
Síntomas descartados (el paciente NO los tiene): {sintomas_negados if sintomas_negados else "ninguno"}
Síntomas ya conocidos (NO volver a preguntar): {list(ya_vistos) if ya_vistos else "ninguno"}
Datos de enfermedades con todos sus síntomas (ordenados por score): {datos_con_sintomas}
"""
        t0 = time.time()
        try:
            evaluacion = _generar_con_reintento(
                self.client, GEMINI_MODEL, prompt_evaluacion, self.config_evaluador_redactor
            ).strip()
            _log('[preguntar] Paso 4+5b evaluador_redactor: %.2fs | resultado=%s',
                        time.time() - t0, evaluacion[:60])
        except Exception as e:
            return str(e), None

        # ── Paso 5a: Diferencial — parsear síntoma + respuesta del output combinado ──
        if evaluacion.startswith("DIFERENCIAL_SINTOMA:"):
            primera_linea, _, respuesta = evaluacion.partition("\n")
            sintoma_dif = primera_linea[len("DIFERENCIAL_SINTOMA:"):].strip()
            respuesta = respuesta.strip()
            if not respuesta:
                respuesta = evaluacion  # fallback: mostrar todo si falta el cuerpo

            nuevo_contexto = {
                "enfermedades_candidatas": datos,
                "sintomas_por_enfermedad": sintomas_por_enf,
                "sintoma_preguntado":      sintoma_dif,
                "sintomas_confirmados":    sintomas_confirmados,
                "sintomas_negados":        sintomas_negados,
                "sintomas_acumulados":     sintomas_acumulados,
            }
            _log("[preguntar] Paso 5a diferencial (fusionado en 4) | sintoma=%s | TOTAL: %.2fs",
                        sintoma_dif, time.time() - t_inicio)
            return respuesta, nuevo_contexto

        # ── Paso 5b: Respuesta generada directamente por el evaluador-redactor ─
        _log("[preguntar] Paso 5b (incluido en 4+5b) | TOTAL: %.2fs",
                    time.time() - t_inicio)
        return evaluacion, None

    def cerrar(self):
        self.db.close()



