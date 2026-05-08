# MEDIC-AI · Asistente Médico Generativo

**MEDIC-AI** es un sistema avanzado de orientación médica basado en evidencia que utiliza una arquitectura de **Graph-RAG** (Generación Aumentada por Recuperación sobre Grafos). Combina el poder de razonamiento de los modelos de lenguaje de Google Gemini con la precisión estructural de una base de datos de grafos Neo4j.

**Link del proyecto:** [https://virtual-medical-assistant-lucasortiz.streamlit.app/](https://virtual-medical-assistant-lucasortiz.streamlit.app/)

---

## Características Principales

* **Análisis Semántico de Síntomas:** Utiliza embeddings para entender el significado detrás de las descripciones del usuario (ej: "cefalea" vs "dolor de cabeza").
* **Razonamiento Diferencial:** Si los síntomas son ambiguos, el sistema realiza preguntas de descarte para refinar el diagnóstico.
* **Búsqueda Híbrida:** Combina búsqueda vectorial (similitud semántica), búsqueda por nombre exacto y generación de Cypher (Text-to-Cypher) para consultas informativas.
* **Ponderación Médica:** Los resultados se ordenan mediante un score que considera la probabilidad de presencia del síntoma, la intensidad reportada por el usuario y la frecuencia poblacional de la enfermedad.
* **Optimización de Costos y Latencia:** Incluye una ruta de detección por regex para saludos que no consume tokens de LLM.

---

## Stack Tecnológico

* **Frontend:** [Streamlit](https://streamlit.io/) (Interfaz web y gestión de estado asíncrona).
* **Motor de IA:** [Google Gemini 3.1 Flash Lite Preview](https://ai.google.dev/) (Agentes especializados para análisis y redacción).
* **Embeddings:** `gemini-embedding-2` (Vectores de 768 dimensiones).
* **Base de Datos de Conocimiento:** [Neo4j](https://neo4j.com/) (Grafo con nodos de Enfermedad, Síntoma y Especialidad).
* **Lenguajes:** Python 3.x.

---

## Arquitectura del Sistema (Flujo de Consulta)

El sistema opera bajo una arquitectura de agentes coordinados en 6 pasos:

1.  **Paso 0 - Ruta Ultra-rápida (Regex):** Detección instantánea de saludos o despedidas sin llamadas a la API de IA.
2.  **Paso 1 - Análisis Unificado:** Un agente clasifica la intención (Consulta vs Funcionalidad) y extrae síntomas con su respectiva intensidad (Leve: 0.7, Normal: 1.0, Fuerte: 1.35).
3.  **Paso 2 - Resolución de Contexto:** Se interpretan las respuestas previas del paciente (Sí/No) para actualizar la lista de síntomas confirmados y negados.
4.  **Paso 3 - Búsqueda en Capas (Graph-RAG):**
    * **Capa Vectorial:** Búsqueda en el índice `sintoma_embeddings` de Neo4j.
    * **Capa de Texto:** Coincidencia exacta de términos.
    * **Text-to-Cypher:** Generación dinámica de consultas para preguntas informativas (ej: "¿Qué trata un dermatólogo?").
5.  **Paso 4 - Evaluación y Redacción:** Un modelo evaluador-redactor analiza las candidatas.
    * **Caso A:** Ganador claro -> Respuesta final con diagnóstico probable y especialidad sugerida.
    * **Caso B:** Ambigüedad -> Generación de un síntoma diferencial para preguntar al paciente.
6.  **Paso 5 - Persistencia:** El estado de la conversación y los síntomas acumulados se guardan en el `session_state` de Streamlit.

---

## Instalación y Configuración

1.  **Clonar el repositorio:**
    ```bash
    git clone https://github.com/tu-usuario/medic-ai.git
    cd medic-ai
    ```

2.  **Instalar dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configurar variables de entorno:**
    Crea un archivo `.env` o configura los `Secrets` en Streamlit con lo siguiente:
    * `GEMINI_API_KEY`: Tu clave de API de Google AI Studio.
    * `NEO4J_URI`: Dirección de tu instancia de Neo4j.
    * `NEO4J_USERNAME`: Usuario de la base de datos.
    * `NEO4J_PASSWORD`: Contraseña de la base de datos.

4.  **Ejecutar la aplicación:**
    ```bash
    streamlit run app.py
    ```

---

## Aviso Legal

Este asistente es una herramienta de **orientación general** basada en inteligencia artificial y no reemplaza el diagnóstico, consejo o tratamiento de un médico certificado. Siempre consulte con un profesional de la salud ante cualquier síntoma o condición médica.

---

**Desarrollado por Lucas Ortiz**
