"""
Script de migración: re-indexa todos los nodos :Sintoma en Neo4j
usando gemini-embedding-001 (reemplaza los vectores de text-embedding-004).

Uso:
    python reindexar_embeddings.py

Requiere .env con:
    GEMINI_API_KEY=...
    NEO4J_URI=...
    NEO4J_USER=...
    NEO4J_PASSWORD=...
"""

import os
import sys
import time
import requests
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USER     = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

EMBEDDING_MODEL  = "gemini-embedding-001"
OUTPUT_DIM       = 768
TASK_TYPE        = "RETRIEVAL_DOCUMENT"  # documentos indexados en la BD
BATCH_DELAY_SEG  = 0.5  # pausa entre llamadas a la API para no saturar el rate limit


def generar_embedding(texto: str) -> list[float]:
    """Genera un vector de OUTPUT_DIM dimensiones y lo normaliza (requerido por gemini-embedding-001)."""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent",
        params={"key": GEMINI_API_KEY},
        json={
            "model": f"models/{EMBEDDING_MODEL}",
            "content": {"parts": [{"text": texto}]},
            "taskType": TASK_TYPE,
            "outputDimensionality": OUTPUT_DIM,
        },
        timeout=30,
    )
    resp.raise_for_status()
    values = resp.json()["embedding"]["values"]
    # Normalización manual requerida para gemini-embedding-001 con dims < 3072
    arr = np.array(values, dtype=np.float32)
    norma = np.linalg.norm(arr)
    if norma > 0:
        arr = arr / norma
    return arr.tolist()


def reindexar():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # 1. Obtener todos los nodos Sintoma
    with driver.session() as session:
        sintomas = session.run("MATCH (s:Sintoma) RETURN id(s) AS nid, s.nombre AS nombre").data()

    total = len(sintomas)
    print(f"Total de nodos Sintoma a re-indexar: {total}")

    errores = []

    for i, row in enumerate(sintomas, start=1):
        nid    = row["nid"]
        nombre = row["nombre"]

        print(f"  [{i}/{total}] {nombre} ...", end=" ", flush=True)

        try:
            vector = generar_embedding(nombre)

            with driver.session() as session:
                session.run(
                    "MATCH (s:Sintoma) WHERE id(s) = $nid SET s.embedding = $vector",
                    nid=nid,
                    vector=vector,
                )
            print("OK")

        except Exception as exc:
            print(f"ERROR: {exc}")
            errores.append({"nombre": nombre, "error": str(exc)})

        # Pausa para respetar rate limits de la API gratuita
        time.sleep(BATCH_DELAY_SEG)

    driver.close()

    # 2. Resumen
    print(f"\nRe-indexación completada: {total - len(errores)}/{total} OK")
    if errores:
        print("Fallaron:")
        for e in errores:
            print(f"  - {e['nombre']}: {e['error']}")
        sys.exit(1)

    # 3. Verificar que el índice vectorial siga apuntando a la propiedad correcta
    print("\nVerificando índice vectorial 'sintoma_embeddings'...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        indices = session.run("SHOW INDEXES YIELD name, type WHERE type = 'VECTOR'").data()
    driver.close()

    nombres = [idx["name"] for idx in indices]
    if "sintoma_embeddings" in nombres:
        print("Índice 'sintoma_embeddings' encontrado. Todo listo.")
    else:
        print("AVISO: No se encontró el índice 'sintoma_embeddings'.")
        print("Creándolo...")
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            session.run("""
                CREATE VECTOR INDEX sintoma_embeddings IF NOT EXISTS
                FOR (s:Sintoma) ON (s.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 768,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
        driver.close()
        print("Índice creado.")


if __name__ == "__main__":
    reindexar()
