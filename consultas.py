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


def _generar_embeddings_sintomas(client, sintomas_json: list) -> list:
    """Añade el vector embedding a cada síntoma extraído para la búsqueda unificada."""
    return [
        {"nombre": item["nombre"], "intensidad": item["intensidad"], "vector": _generar_embedding(client, item["nombre"])}
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
4. NUNCA generes operaciones de escritura (CREATE, DELETE, MERGE, SET, REMOVE, DROP). Solo consultas de lectura.

Contexto del flujo:
- Un agente evaluador analiza los datos que devuelves para determinar qué enfermedad corresponde al paciente.
- Si el evaluador no tiene suficiente información para decidir, le hace UNA pregunta al paciente pidiendo un síntoma adicional.
- Cuando el paciente responde esa pregunta, el historial lo incluye. En ese caso, combiná TODOS los síntomas mencionados en la conversación para generar una query más específica que ayude al evaluador a tomar la decisión.""",
        )

        # Configuración del modelo 2: Evalúa qué enfermedad se adecúa mejor al paciente
        self.config_evaluador = types.GenerateContentConfig(
            system_instruction="""Eres un evaluador médico. Recibes la consulta de un paciente y datos de enfermedades de una base de datos.

Tu tarea es determinar qué enfermedad se adecúa mejor al cuadro del paciente.

Reglas estrictas:
1. Si los datos apuntan claramente a UNA enfermedad (score muy superior al resto, cuadro inequívoco,
   o síntomas descartados eliminan las demás candidatas), responde:
   DECISION: <nombre exacto de la enfermedad tal como aparece en los datos>

2. Si hay 2 o más enfermedades que compiten (scores similares, síntomas compartidos, cuadro ambiguo),
   responde listando ÚNICAMENTE los nombres de las candidatas separados por coma:
   DIFERENCIAL: <EnfA>, <EnfB>, <EnfC>

3. Orden de preferencia de gravedad cuando el paciente no la especifica: leve > moderada > grave > crítica.

4. Ten en cuenta los síntomas descartados para eliminar candidatas que los requieren.

5. Devuelve ÚNICAMENTE el prefijo y el contenido. Sin texto adicional.""",
        )

        # Configuración del modelo 3: Convierte datos crudos en respuesta humana
        self.config_redactor = types.GenerateContentConfig(
            system_instruction="""Eres un asistente médico empático. Explica resultados de bases de datos
médicas de forma clara y amigable para pacientes no especializados.
Responde siempre en español y sugiere consultar a un médico para diagnósticos definitivos.""",
        )

        # Configuración del modelo 0a: Clasifica la intención del mensaje
        self.config_clasificador = types.GenerateContentConfig(
            system_instruction="""Clasificas la intención de mensajes dirigidos a un asistente médico virtual.

Devuelve ÚNICAMENTE una de estas etiquetas, sin texto adicional:
- SALUDO           → el mensaje es solo un saludo o expresión social (hola, buenas, gracias, etc.)
- FUNCIONALIDAD    → el mensaje pregunta qué puede hacer, cómo funciona o para qué sirve el asistente
- SALUDO_FUNC      → el mensaje combina saludo y pregunta por funcionalidad
- CONSULTA         → el mensaje describe síntomas, enfermedades, medicamentos u otra consulta médica

Si el mensaje mezcla saludo/funcionalidad CON una consulta médica, devuelve CONSULTA.""",
        )

        # Configuración del modelo 0b: Responde saludos y preguntas de funcionalidad
        self.config_conversacional = types.GenerateContentConfig(
            system_instruction="""Eres MEDIC-AI, un asistente de orientación médica con inteligencia artificial.
Respondes en español, de forma cálida y concisa.

Si el usuario saluda → devuelve un saludo cordial y preséntate brevemente.
Si pregunta por tu funcionalidad → explica que podés relacionar síntomas con posibles enfermedades,
  sugerir la especialidad médica adecuada y orientar sobre nivel de gravedad, siempre recordando que
  no reemplazás a un médico certificado.
Si hace ambas cosas → saluda y explica tu funcionalidad en el mismo mensaje.
No incluyas diagnósticos ni información médica específica en esta respuesta.""",
        )

        # Configuración del extractor de síntomas con intensidad
        self.config_extractor_sintomas = types.GenerateContentConfig(
            system_instruction="""Extraes síntomas y su intensidad del texto de un paciente.

Reglas de intensidad (I):
- 'un poco', 'leve', 'apenas' → I = 0.7
- Sin adjetivos o 'tengo...' → I = 1.0
- 'mucho', 'muy', 'fuerte', 'muchísimo' → I = 1.35

Devuelve ÚNICAMENTE una lista JSON con el formato: [{"nombre": "Sintoma", "intensidad": I}]
Sin texto extra, sin bloques de código markdown. Si no hay síntomas, devuelve: []""",
        )

        # Config: selecciona el síntoma más diferenciador entre las candidatas
        self.config_selector_sintoma = types.GenerateContentConfig(
            system_instruction="""Eres un experto en diagnóstico diferencial médico.

Recibes un JSON con:
- "candidatas": diccionario {enfermedad: [lista de síntomas]} de las enfermedades en disputa
- "ya_preguntados": síntomas ya conocidos o preguntados (NO repetir)

Tu tarea: elegir el síntoma con MAYOR poder diferenciador entre las candidatas.

Criterios (en orden de prioridad):
1. Presente en ALGUNAS candidatas pero AUSENTE en otras (máxima diferenciación)
2. Muy específico de 1 o 2 enfermedades concretas
3. Fácil de identificar por el paciente (visible, palpable, concreto)
4. NO puede estar en "ya_preguntados"

Devuelve ÚNICAMENTE el nombre del síntoma elegido, tal como aparece en los datos. Sin texto adicional.""",
        )

        # Config: redacta la respuesta diferencial mostrando candidatas + pregunta
        self.config_redactor_diferencial = types.GenerateContentConfig(
            system_instruction="""Eres un asistente médico empático.

Recibes un JSON con:
- "consulta_original": lo que describió el paciente
- "candidatas": lista de enfermedades posibles con su gravedad
- "sintoma_a_preguntar": el síntoma clave para diferenciarlas

Redacta una respuesta que:
1. Reconozca los síntomas que describió el paciente
2. Explique que sus síntomas podrían corresponder a varias condiciones y las liste brevemente con su nivel de gravedad
3. Indique que para determinar cuál es más probable necesitas una información más
4. Pregunte de forma directa y sencilla si el paciente presenta el síntoma en "sintoma_a_preguntar"

Usa lenguaje simple, empático, sin tecnicismos. Responde en español.
Siempre recuerda que esto es solo orientación y que debe consultar a un médico.""",
        )

    def preguntar(self, texto_usuario: str, historial: list = None,
                  contexto_diferencial: dict = None) -> tuple:
        """Procesa la consulta del usuario.
        Retorna (respuesta: str, nuevo_contexto_diferencial: dict | None).
        nuevo_contexto_diferencial es None cuando no hay diagnóstico diferencial activo.
        """
        import json as _json

        # ── Paso 0: Clasificar intención ─────────────────────────────────────
        try:
            intencion = _generar_con_reintento(
                self.client, "gemini-3.1-flash-lite-preview", texto_usuario, self.config_clasificador
            ).strip().upper()
        except Exception:
            intencion = "CONSULTA"

        if intencion in ("SALUDO", "FUNCIONALIDAD", "SALUDO_FUNC"):
            try:
                return _generar_con_reintento(
                    self.client, "gemini-3.1-flash-lite-preview", texto_usuario, self.config_conversacional
                ), None
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

        # ── Paso 1: Extraer síntomas del input actual ─────────────────────────
        sintomas_nuevos = []
        try:
            sintomas_json_str = _generar_con_reintento(
                self.client, "gemini-3.1-flash-lite-preview", texto_usuario, self.config_extractor_sintomas
            ).strip()
            sintomas_nuevos = _json.loads(sintomas_json_str)
        except Exception:
            sintomas_nuevos = []

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
            try:
                sintomas_con_vector = _generar_embeddings_sintomas(self.client, sintomas_acumulados)
                datos = self.db.buscar_con_intensidad_vectorial(sintomas_con_vector)
            except Exception:
                datos = []

        # --- Fallback Text-to-Cypher si el vector no dio resultados ---
        if not datos:
            try:
                cypher_query = _generar_con_reintento(
                    self.client, "gemini-3.1-flash-lite-preview", contexto, self.config_traductor
                ).strip()
            except Exception as e:
                return str(e), None

            if cypher_query.lower() == "error":
                return (
                    "Lo siento, mi base de datos solo contiene información sobre enfermedades, "
                    "síntomas y especialidades médicas. ¿Puedes reformular tu pregunta?"
                ), None

            if not _es_query_segura(cypher_query):
                return "Lo siento, no puedo procesar esa solicitud.", None

            try:
                datos = self.db.ejecutar_consulta(cypher_query)
            except ServiceUnavailable:
                return "No se pudo conectar a la base de datos. Por favor intenta de nuevo más tarde.", None
            except CypherSyntaxError as e:
                return f"Error de sintaxis en la query generada.\n\nQuery: `{cypher_query}`\n\nError: {e}", None
            except Exception as e:
                return f"Ocurrió un error inesperado al consultar la base de datos: {e}", None

            if not datos:
                return (
                    "No encontré condiciones que coincidan con los síntomas descritos. "
                    "¿Puedes dar más detalles o mencionar otros síntomas?"
                ), None

        # ── Paso 4: Evaluador — ¿decisión clara o diagnóstico diferencial? ────
        prompt_evaluacion = f"""
Consulta del paciente: "{texto_usuario}"
Síntomas descartados (el paciente NO los tiene): {sintomas_negados if sintomas_negados else "ninguno"}
Datos encontrados (ordenados por score de probabilidad ponderada): {datos}
"""
        try:
            evaluacion = _generar_con_reintento(
                self.client, "gemini-3.1-flash-lite-preview", prompt_evaluacion, self.config_evaluador
            ).strip()
        except Exception as e:
            return str(e), None

        # ── Paso 5a: Modo diagnóstico diferencial ─────────────────────────────
        if evaluacion.startswith("DIFERENCIAL:"):
            partes_raw = evaluacion[len("DIFERENCIAL:"):].strip().split(",")
            nombres_candidatas = [p.strip() for p in partes_raw if p.strip()]

            # Filtrar datos a las candidatas que identificó el evaluador
            candidatas = [
                d for d in datos
                if any(
                    nc.lower() in d["enfermedad"].lower() or d["enfermedad"].lower() in nc.lower()
                    for nc in nombres_candidatas
                )
            ]
            if not candidatas:
                candidatas = datos[:min(3, len(datos))]

            # Traer TODOS los síntomas de cada candidata desde Neo4j
            try:
                sintomas_por_enf = self.db.obtener_sintomas_enfermedades(
                    [d["enfermedad"] for d in candidatas]
                )
            except Exception:
                sintomas_por_enf = {}

            # Síntomas ya conocidos → no repetir preguntas
            ya_vistos = nombres_acumulados | {s.lower() for s in sintomas_negados}

            # Seleccionar el síntoma más diferenciador vía LLM
            prompt_selector = _json.dumps(
                {"candidatas": sintomas_por_enf, "ya_preguntados": list(ya_vistos)},
                ensure_ascii=False,
            )
            try:
                sintoma_dif = _generar_con_reintento(
                    self.client, "gemini-3.1-flash-lite-preview",
                    prompt_selector, self.config_selector_sintoma
                ).strip()
            except Exception:
                sintoma_dif = _seleccionar_sintoma_fallback(sintomas_por_enf, ya_vistos)

            # Guardar estado diferencial para el próximo turno
            nuevo_contexto = {
                "enfermedades_candidatas": candidatas,
                "sintomas_por_enfermedad": sintomas_por_enf,
                "sintoma_preguntado":      sintoma_dif,
                "sintomas_confirmados":    sintomas_confirmados,
                "sintomas_negados":        sintomas_negados,
                "sintomas_acumulados":     sintomas_acumulados,
            }

            # Redactar respuesta diferencial (candidatas + pregunta del síntoma)
            prompt_redaccion_dif = _json.dumps(
                {
                    "consulta_original": texto_usuario,
                    "candidatas": [
                        {"enfermedad": d["enfermedad"], "gravedad": d["gravedad"]}
                        for d in candidatas
                    ],
                    "sintoma_a_preguntar": sintoma_dif,
                },
                ensure_ascii=False,
            )
            try:
                respuesta = _generar_con_reintento(
                    self.client, "gemini-3.1-flash-lite-preview",
                    prompt_redaccion_dif, self.config_redactor_diferencial
                )
            except Exception as e:
                respuesta = str(e)

            return respuesta, nuevo_contexto

        # ── Paso 5b: Decisión única — redactar respuesta final ────────────────
        if evaluacion.startswith("DECISION:"):
            nombre_seleccionado = evaluacion[len("DECISION:"):].strip()
            datos_filtrados = [d for d in datos if nombre_seleccionado.lower() in str(d).lower()]
            datos_para_redactor = datos_filtrados if datos_filtrados else datos
        else:
            datos_para_redactor = datos

        prompt_redaccion = f"""
El usuario realizó esta consulta: "{texto_usuario}"
Los datos encontrados en la base de datos médica son: {datos_para_redactor}

Redacta una respuesta clara y amigable basada ÚNICAMENTE en esos datos.
"""
        try:
            return _generar_con_reintento(
                self.client, "gemini-3.1-flash-lite-preview", prompt_redaccion, self.config_redactor
            ), None
        except Exception as e:
            return str(e), None

    def cerrar(self):
        self.db.close()


