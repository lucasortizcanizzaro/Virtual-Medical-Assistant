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
# y las credenciales se leen desde st.secrets (ver mÃ¡s abajo).
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Modelo LLM utilizado en todos los agentes
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

# PatrÃ³n que detecta operaciones de escritura en Cypher
_CYPHER_WRITE_PATTERN = re.compile(
    r'\b(create|delete|detach|merge|set|remove|drop|call)\b',
    re.IGNORECASE
)


def _sin_tildes(texto: str) -> str:
    """Elimina tildes y diacrÃ­ticos. Ej: 'diarrÃ©a' â†’ 'diarrea'."""
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
    """AÃ±ade el vector embedding a cada sÃ­ntoma extraÃ­do para la bÃºsqueda unificada."""
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
            # Error 500 del servidor de Gemini â€” suele ser transitorio
            if intento < max_intentos - 1:
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError("El servidor de Gemini no estÃ¡ disponible en este momento. Intenta de nuevo en unos segundos.")
        except ClientError as e:
            if e.code == 429 and intento < max_intentos - 1:
                time.sleep(espera)
                espera *= 2  # backoff exponencial: 5s, 10s, 20s
                continue
            elif e.code == 429:
                raise RuntimeError("LÃ­mite de solicitudes a la API de Gemini alcanzado. Espera unos segundos e intenta de nuevo.")
            elif e.code in (401, 403):
                raise RuntimeError("API key de Gemini invÃ¡lida o sin permisos. Verifica tu configuraciÃ³n.")
            else:
                raise


def _seleccionar_sintoma_fallback(sintomas_por_enf: dict, ya_vistos: set) -> str:
    """Elige el sÃ­ntoma con mayor poder diferenciador (ni en todas ni en ninguna candidata)."""
    conteo: dict[str, int] = {}
    for syms in sintomas_por_enf.values():
        for s in syms:
            key = s.lower()
            if key not in ya_vistos:
                conteo[s] = conteo.get(s, 0) + 1
    if not conteo:
        return "algÃºn sÃ­ntoma adicional"
    total = len(sintomas_por_enf)
    # El mejor diferenciador estÃ¡ en ~mitad de las enfermedades
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
        # Cliente Ãºnico de la nueva SDK
        self.client = genai.Client(api_key=_get_secret("GEMINI_API_KEY"))

        # La conexiÃ³n a Neo4j se configura desde secrets (Cloud) o .env (local)
        self.db = MedicoDB(
            uri=_get_secret("NEO4J_URI") or "bolt://localhost:7687",
            user=_get_secret("NEO4J_USERNAME") or "neo4j",
            password=_get_secret("NEO4J_PASSWORD"),
        )

        # Macro de normalizaciÃ³n reutilizable en el system_instruction
        _norm = lambda campo: (
            f"replace(replace(replace(replace(replace(replace(replace("
            f"toLower({campo}),'Ã¡','a'),'Ã©','e'),'Ã­','i'),'Ã³','o'),'Ãº','u'),'Ã±','n'),'Ã¼','u')"
        )

        # ConfiguraciÃ³n del modelo 1: Traduce lenguaje natural â†’ Cypher
        self.config_traductor = types.GenerateContentConfig(
            system_instruction=f"""Eres un experto en Neo4j. Traduces lenguaje natural a consultas Cypher.
Esquema de la base de datos:
- Nodos: Enfermedad {{nombre, gravedad}}, Sintoma {{nombre, habitualidad}}, Especialidad {{nombre}}
- Relaciones: (Enfermedad)-[:GENERA]->(Sintoma), (Especialidad)-[:TRATA]->(Enfermedad)

Reglas estrictas:
1. Devuelve SOLO el cÃ³digo Cypher. Sin explicaciones ni bloques de cÃ³digo markdown.
2. Para comparaciones de texto SIEMPRE normaliza ambos lados quitando tildes y usando minÃºsculas:
   {_norm("n.nombre")} CONTAINS {_norm("'valor'")}
3. Si la pregunta no puede responderse con este esquema, devuelve exactamente: error
4. NUNCA generes operaciones de escritura (CREATE, DELETE, MERGE, SET, REMOVE, DROP). Solo consultas de lectura.

Contexto del flujo:
- Un agente evaluador analiza los datos que devuelves para determinar quÃ© enfermedad corresponde al paciente.
- Si el evaluador no tiene suficiente informaciÃ³n para decidir, le hace UNA pregunta al paciente pidiendo un sÃ­ntoma adicional.
- Cuando el paciente responde esa pregunta, el historial lo incluye. En ese caso, combinÃ¡ TODOS los sÃ­ntomas mencionados en la conversaciÃ³n para generar una query mÃ¡s especÃ­fica que ayude al evaluador a tomar la decisiÃ³n.""",
        )

        # ConfiguraciÃ³n del modelo 2: EvalÃºa quÃ© enfermedad se adecÃºa mejor al paciente
        self.config_evaluador = types.GenerateContentConfig(
            system_instruction="""Eres un evaluador mÃ©dico. Recibes la consulta de un paciente y datos de enfermedades de una base de datos.

Tu tarea es determinar quÃ© enfermedad se adecÃºa mejor al cuadro del paciente.

Reglas estrictas:
1. Si los datos apuntan claramente a UNA enfermedad (score muy superior al resto, cuadro inequÃ­voco,
   o sÃ­ntomas descartados eliminan las demÃ¡s candidatas), responde:
   DECISION: <nombre exacto de la enfermedad tal como aparece en los datos>

2. Si hay 2 o mÃ¡s enfermedades que compiten (scores similares, sÃ­ntomas compartidos, cuadro ambiguo),
   responde listando ÃšNICAMENTE los nombres de las candidatas separados por coma:
   DIFERENCIAL: <EnfA>, <EnfB>, <EnfC>

3. Orden de preferencia de gravedad cuando el paciente no la especifica: leve > moderada > grave > crÃ­tica.

4. Ten en cuenta los sÃ­ntomas descartados para eliminar candidatas que los requieren.

5. Devuelve ÃšNICAMENTE el prefijo y el contenido. Sin texto adicional.""",
        )

        # ConfiguraciÃ³n del modelo 3: Convierte datos crudos en respuesta humana
        self.config_redactor = types.GenerateContentConfig(
            system_instruction="""Eres un asistente mÃ©dico empÃ¡tico. Explica resultados de bases de datos
mÃ©dicas de forma clara y amigable para pacientes no especializados.
Responde siempre en espaÃ±ol y sugiere consultar a un mÃ©dico para diagnÃ³sticos definitivos.""",
        )

        # Config unificado: clasifica intenciÃ³n Y extrae sÃ­ntomas en una sola llamada
        self.config_analizador = types.GenerateContentConfig(
            system_instruction="""Analizas mensajes dirigidos a un asistente mÃ©dico virtual y hacÃ©s dos tareas a la vez.

TAREA 1 â€” Clasificar intenciÃ³n:
- SALUDO        â†’ solo saludo o expresiÃ³n social (hola, gracias, etc.)
- FUNCIONALIDAD â†’ pregunta quÃ© puede hacer el asistente o cÃ³mo funciona
- SALUDO_FUNC   â†’ combina saludo y pregunta de funcionalidad
- CONSULTA      â†’ describe sÃ­ntomas, enfermedades, medicamentos u otra consulta mÃ©dica
Si mezcla saludo/funcionalidad CON consulta mÃ©dica â†’ CONSULTA.

TAREA 2 â€” Extraer sÃ­ntomas con intensidad:
- 'un poco', 'leve', 'apenas' â†’ intensidad 0.7
- sin adjetivos o 'tengo...'  â†’ intensidad 1.0
- 'mucho', 'muy', 'fuerte', 'muchÃ­simo' â†’ intensidad 1.35

Devuelve ÃšNICAMENTE un objeto JSON con este formato exacto, sin texto adicional ni bloques markdown:
{"intencion": "CONSULTA", "sintomas": [{"nombre": "Sintoma", "intensidad": 1.0}]}

Si la intenciÃ³n no es CONSULTA, "sintomas" debe ser [].""",
        )

        # ConfiguraciÃ³n del modelo 0b: Responde saludos y preguntas de funcionalidad
        self.config_conversacional = types.GenerateContentConfig(
            system_instruction="""Eres MEDIC-AI, un asistente de orientaciÃ³n mÃ©dica con inteligencia artificial.
Respondes en espaÃ±ol, de forma cÃ¡lida y concisa.

Si el usuario saluda â†’ devuelve un saludo cordial y presÃ©ntate brevemente.
Si pregunta por tu funcionalidad â†’ explica que podÃ©s relacionar sÃ­ntomas con posibles enfermedades,
  sugerir la especialidad mÃ©dica adecuada y orientar sobre nivel de gravedad, siempre recordando que
  no reemplazÃ¡s a un mÃ©dico certificado.
Si hace ambas cosas â†’ saluda y explica tu funcionalidad en el mismo mensaje.
No incluyas diagnÃ³sticos ni informaciÃ³n mÃ©dica especÃ­fica en esta respuesta.""",
        )

        # Config: selecciona el sÃ­ntoma mÃ¡s diferenciador entre las candidatas
        self.config_selector_sintoma = types.GenerateContentConfig(
            system_instruction="""Eres un experto en diagnÃ³stico diferencial mÃ©dico.

Recibes un JSON con:
- "candidatas": diccionario {enfermedad: [lista de sÃ­ntomas]} de las enfermedades en disputa
- "ya_preguntados": sÃ­ntomas ya conocidos o preguntados (NO repetir)

Tu tarea: elegir el sÃ­ntoma con MAYOR poder diferenciador entre las candidatas.

Criterios (en orden de prioridad):
1. Presente en ALGUNAS candidatas pero AUSENTE en otras (mÃ¡xima diferenciaciÃ³n)
2. Muy especÃ­fico de 1 o 2 enfermedades concretas
3. FÃ¡cil de identificar por el paciente (visible, palpable, concreto)
4. NO puede estar en "ya_preguntados"

Devuelve ÃšNICAMENTE el nombre del sÃ­ntoma elegido, tal como aparece en los datos. Sin texto adicional.""",
        )

        # Config: redacta la respuesta diferencial mostrando candidatas + pregunta
        self.config_redactor_diferencial = types.GenerateContentConfig(
            system_instruction="""Eres un asistente mÃ©dico empÃ¡tico.

Recibes un JSON con:
- "consulta_original": lo que describiÃ³ el paciente
- "candidatas": lista de enfermedades posibles con su gravedad
- "sintoma_a_preguntar": el sÃ­ntoma clave para diferenciarlas

Redacta una respuesta que:
1. Reconozca los sÃ­ntomas que describiÃ³ el paciente
2. Explique que sus sÃ­ntomas podrÃ­an corresponder a varias condiciones y las liste brevemente con su nivel de gravedad
3. Indique que para determinar cuÃ¡l es mÃ¡s probable necesitas una informaciÃ³n mÃ¡s
4. Pregunte de forma directa y sencilla si el paciente presenta el sÃ­ntoma en "sintoma_a_preguntar"

Usa lenguaje simple, empÃ¡tico, sin tecnicismos. Responde en espaÃ±ol.
Siempre recuerda que esto es solo orientaciÃ³n y que debe consultar a un mÃ©dico.""",
        )

    def preguntar(self, texto_usuario: str, historial: list = None,
                  contexto_diferencial: dict = None) -> tuple:
        """Procesa la consulta del usuario.
        Retorna (respuesta: str, nuevo_contexto_diferencial: dict | None).
        nuevo_contexto_diferencial es None cuando no hay diagnÃ³stico diferencial activo.
        """
        import json as _json

        t_inicio = time.time()

        # â”€â”€ Paso 0+1: Clasificar intenciÃ³n y extraer sÃ­ntomas (llamada unificada) â”€â”€
        intencion = "CONSULTA"
        sintomas_nuevos = []
        try:
            analisis_str = _generar_con_reintento(
                self.client, GEMINI_MODEL, texto_usuario, self.config_analizador
            ).strip()
            analisis = _json.loads(analisis_str)
            intencion = str(analisis.get("intencion", "CONSULTA")).strip().upper()
            candidatos = analisis.get("sintomas", [])
            if isinstance(candidatos, list) and all(
                isinstance(item, dict) and "nombre" in item and "intensidad" in item
                for item in candidatos
            ):
                sintomas_nuevos = candidatos
        except Exception:
            intencion = "CONSULTA"
        logger.info("[preguntar] Paso 1 analizador: %.2fs | intencion=%s | sintomas=%s",
                    time.time() - t_inicio, intencion, [s["nombre"] for s in sintomas_nuevos])

        if intencion in ("SALUDO", "FUNCIONALIDAD", "SALUDO_FUNC"):
            try:
                t0 = time.time()
                resp = _generar_con_reintento(
                    self.client, GEMINI_MODEL, texto_usuario, self.config_conversacional
                )
                logger.info("[preguntar] conversacional: %.2fs | TOTAL: %.2fs",
                            time.time() - t0, time.time() - t_inicio)
                return resp, None
            except Exception as e:
                return str(e), None

        # â”€â”€ Flujo mÃ©dico â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Paso 2: Resolver y actualizar contexto diferencial previo â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sintomas_confirmados = list((contexto_diferencial or {}).get("sintomas_confirmados", []))
        sintomas_negados     = list((contexto_diferencial or {}).get("sintomas_negados", []))
        sintomas_acumulados  = list((contexto_diferencial or {}).get("sintomas_acumulados", []))

        if contexto_diferencial and "sintoma_preguntado" in contexto_diferencial:
            sintoma_preguntado = contexto_diferencial["sintoma_preguntado"]
            resp_lower = f" {texto_usuario.lower()} "

            _palabras_si = {
                "si", "sÃ­", "yes", "tengo", "siento", "me duele", "noto",
                "tambiÃ©n", "tambien", "claro", "correcto", "exacto",
                "efectivamente", "presenta", "suelo", "a veces",
            }
            _palabras_no = {
                "no", "tampoco", "nunca", "jamas", "jamÃ¡s",
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

        # Acumular: sÃ­ntomas previos + nuevos del input + confirmados por el usuario
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

        # â”€â”€ Paso 3: BÃºsqueda vectorial con todos los sÃ­ntomas acumulados â”€â”€â”€â”€â”€â”€
        datos = []
        if sintomas_acumulados:
            t0 = time.time()
            try:
                sintomas_con_vector = _generar_embeddings_sintomas(self.client, sintomas_acumulados)
                t_embed = time.time() - t0
                datos = self.db.buscar_con_intensidad_vectorial(sintomas_con_vector)
                logger.info("[preguntar] Paso 3 vectorial: embed=%.2fs neo4j=%.2fs resultados=%d", t_embed, time.time() - t0 - t_embed, len(datos))
            except Exception as e:
                logger.warning("[preguntar] Paso 3 vectorial ERROR: %s", e)
                datos = []

        # --- Ruta 2: Fallback por nombre exacto si vector no dio resultados ---
        if not datos and sintomas_acumulados:
            t0 = time.time()
            try:
                datos = self.db.obtener_ranking_enfermedades(
                    [s["nombre"] for s in sintomas_acumulados]
                )
                logger.info("[preguntar] Ruta 2 nombre exacto: %.2fs resultados=%d", time.time() - t0, len(datos))
            except Exception as e:
                logger.warning("[preguntar] Ruta 2 ERROR: %s", e)
                datos = []

        # --- Ruta 3: Text-to-Cypher para preguntas sin sÃ­ntomas (informativas) ---
        if not datos and not sintomas_acumulados:
            t0 = time.time()
            try:
                cypher_query = _generar_con_reintento(
                    self.client, GEMINI_MODEL, contexto, self.config_traductor
                ).strip()
                logger.info("[preguntar] Ruta 3 traductor: %.2fs", time.time() - t0)
            except Exception as e:
                return str(e), None

            if cypher_query.lower() == "error":
                return (
                    "Lo siento, mi base de datos solo contiene informaciÃ³n sobre enfermedades, "
                    "sÃ­ntomas y especialidades mÃ©dicas. Â¿Puedes reformular tu pregunta?"
                ), None

            if not _es_query_segura(cypher_query):
                return "Lo siento, no puedo procesar esa solicitud.", None

            try:
                datos = self.db.ejecutar_consulta(cypher_query)
            except ServiceUnavailable:
                return "No se pudo conectar a la base de datos. Por favor intenta de nuevo mÃ¡s tarde.", None
            except (CypherSyntaxError, Exception):
                datos = []

        # Normalizar datos: asegurar que todos los registros tengan la clave "enfermedad"
        datos = [d for d in datos if isinstance(d, dict) and d.get("enfermedad")]

        if not datos:
            return (
                "No encontrÃ© condiciones que coincidan con los sÃ­ntomas descritos. "
                "Â¿Puedes dar mÃ¡s detalles o mencionar otros sÃ­ntomas?"
            ), None

        # â”€â”€ Paso 4: Evaluador â€” Â¿decisiÃ³n clara o diagnÃ³stico diferencial? â”€â”€â”€â”€
        prompt_evaluacion = f"""
Consulta del paciente: "{texto_usuario}"
SÃ­ntomas descartados (el paciente NO los tiene): {sintomas_negados if sintomas_negados else "ninguno"}
Datos encontrados (ordenados por score de probabilidad ponderada): {datos}
"""
        t0 = time.time()
        try:
            evaluacion = _generar_con_reintento(
                self.client, GEMINI_MODEL, prompt_evaluacion, self.config_evaluador
            ).strip()
            logger.info('[preguntar] Paso 4 evaluador: %.2fs | resultado=%s',
                        time.time() - t0, evaluacion[:60])
        except Exception as e:
            return str(e), None

        # â”€â”€ Paso 5a: Modo diagnÃ³stico diferencial â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if evaluacion.startswith("DIFERENCIAL:"):
            partes_raw = evaluacion[len("DIFERENCIAL:"):].strip().split(",")
            nombres_candidatas = [p.strip() for p in partes_raw if p.strip()]

            # Filtrar datos a las candidatas que identificÃ³ el evaluador
            candidatas = [
                d for d in datos
                if any(
                    nc.lower() in d["enfermedad"].lower() or d["enfermedad"].lower() in nc.lower()
                    for nc in nombres_candidatas
                )
            ]
            if not candidatas:
                candidatas = datos[:min(3, len(datos))]

            # Traer TODOS los sÃ­ntomas de cada candidata desde Neo4j
            try:
                sintomas_por_enf = self.db.obtener_sintomas_enfermedades(
                    [d["enfermedad"] for d in candidatas]
                )
            except Exception:
                sintomas_por_enf = {}

            # SÃ­ntomas ya conocidos â†’ no repetir preguntas
            ya_vistos = nombres_acumulados | {s.lower() for s in sintomas_negados}

            # Seleccionar el sÃ­ntoma mÃ¡s diferenciador vÃ­a LLM
            prompt_selector = _json.dumps(
                {"candidatas": sintomas_por_enf, "ya_preguntados": list(ya_vistos)},
                ensure_ascii=False,
            )
            t0 = time.time()
            try:
                sintoma_dif = _generar_con_reintento(
                    self.client, GEMINI_MODEL,
                    prompt_selector, self.config_selector_sintoma
                ).strip()
                logger.info("[preguntar] Paso 5a selector: %.2fs | sintoma=%s",
                            time.time() - t0, sintoma_dif)
            except Exception:
                sintoma_dif = _seleccionar_sintoma_fallback(sintomas_por_enf, ya_vistos)
                logger.info("[preguntar] Paso 5a selector FALLBACK: %s", sintoma_dif)

            # Guardar estado diferencial para el prÃ³ximo turno
            nuevo_contexto = {
                "enfermedades_candidatas": candidatas,
                "sintomas_por_enfermedad": sintomas_por_enf,
                "sintoma_preguntado":      sintoma_dif,
                "sintomas_confirmados":    sintomas_confirmados,
                "sintomas_negados":        sintomas_negados,
                "sintomas_acumulados":     sintomas_acumulados,
            }

            # Redactar respuesta diferencial (candidatas + pregunta del sÃ­ntoma)
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
            t0 = time.time()
            try:
                respuesta = _generar_con_reintento(
                    self.client, GEMINI_MODEL,
                    prompt_redaccion_dif, self.config_redactor_diferencial
                )
                logger.info("[preguntar] Paso 5a redactor_dif: %.2fs | TOTAL: %.2fs",
                            time.time() - t0, time.time() - t_inicio)
            except Exception as e:
                respuesta = str(e)

            return respuesta, nuevo_contexto

        # â”€â”€ Paso 5b: DecisiÃ³n Ãºnica â€” redactar respuesta final â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if evaluacion.startswith("DECISION:"):
            nombre_seleccionado = evaluacion[len("DECISION:"):].strip()
            datos_filtrados = [d for d in datos if nombre_seleccionado.lower() in str(d).lower()]
            datos_para_redactor = datos_filtrados if datos_filtrados else datos
        else:
            datos_para_redactor = datos

        prompt_redaccion = f"""
El usuario realizÃ³ esta consulta: "{texto_usuario}"
Los datos encontrados en la base de datos mÃ©dica son: {datos_para_redactor}

Redacta una respuesta clara y amigable basada ÃšNICAMENTE en esos datos.
"""
        t0 = time.time()
        try:
            resp = _generar_con_reintento(
                self.client, GEMINI_MODEL, prompt_redaccion, self.config_redactor
            )
            logger.info("[preguntar] Paso 5b redactor: %.2fs | TOTAL: %.2fs",
                        time.time() - t0, time.time() - t_inicio)
            return resp, None
        except Exception as e:
            return str(e), None

    def cerrar(self):
        self.db.close()



