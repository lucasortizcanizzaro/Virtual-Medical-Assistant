from neo4j import GraphDatabase

class MedicoDB:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def ejecutar_consulta(self, cypher_query: str) -> list:
        """Ejecuta cualquier consulta Cypher y devuelve una lista de diccionarios."""
        with self.driver.session() as session:
            result = session.run(cypher_query)
            return [record.data() for record in result]

    def buscar_por_vector(self, index_name: str, vector: list, top_k: int = 5) -> list:
        """Búsqueda semántica: dado un vector, devuelve enfermedades cuyos síntomas son similares."""
        cypher = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $vector)
        YIELD node AS sintoma, score
        MATCH (e:Enfermedad)-[:GENERA]->(sintoma)
        OPTIONAL MATCH (esp:Especialidad)-[:TRATA]->(e)
        RETURN e.nombre AS enfermedad,
               e.gravedad AS gravedad,
               collect(DISTINCT sintoma.nombre) AS sintomas,
               collect(DISTINCT esp.nombre) AS especialidades,
               max(score) AS relevancia
        ORDER BY relevancia DESC
        """
        with self.driver.session() as session:
            result = session.run(cypher, index_name=index_name, top_k=top_k, vector=vector)
            return [record.data() for record in result]

    def buscar_con_intensidad_vectorial(self, sintomas_con_vector: list) -> list:
        """Búsqueda unificada: por cada síntoma busca el nodo más cercano por vector
        y pondera sensibilidad clínica × intensidad del usuario × prevalencia poblacional.
        sintomas_con_vector: [{"nombre": "tos", "intensidad": 1.35, "vector": [...]}]
        """
        cypher = """
        UNWIND $datos AS item
        CALL db.index.vector.queryNodes('sintoma_embeddings', 1, item.vector)
        YIELD node AS sintoma, score
        WHERE score >= 0.75
        MATCH (e:Enfermedad)-[rel:GENERA]->(sintoma)
        OPTIONAL MATCH (esp:Especialidad)-[:TRATA]->(e)
        WITH e, rel, item, sintoma, esp
        WITH e,
             sum(rel.probabilidad_presencia * item.intensidad) AS sensibilidad_ponderada,
             collect(DISTINCT sintoma.nombre) AS sintomas,
             collect(DISTINCT esp.nombre) AS especialidades
        RETURN e.nombre AS enfermedad,
               e.gravedad AS gravedad,
               sintomas,
               especialidades,
               (sensibilidad_ponderada * e.frecuencia) AS score_final
        ORDER BY score_final DESC
        LIMIT 5
        """
        with self.driver.session() as session:
            result = session.run(cypher, datos=sintomas_con_vector)
            return [record.data() for record in result]

    def obtener_ranking_enfermedades(self, lista_sintomas: list) -> list:
        """Top 3 enfermedades por score = suma(sensibilidad) × frecuencia poblacional."""
        query = """
        MATCH (e:Enfermedad)-[rel:GENERA]->(s:Sintoma)
        WHERE toLower(s.nombre) IN $sintomas
        WITH e, sum(rel.probabilidad_presencia) AS suma_sensibilidad
        RETURN e.nombre AS enfermedad,
               e.gravedad AS gravedad,
               (suma_sensibilidad * e.frecuencia) AS score_final
        ORDER BY score_final DESC
        LIMIT 3
        """
        sintomas_busqueda = [s.lower() for s in lista_sintomas]
        with self.driver.session() as session:
            result = session.run(query, sintomas=sintomas_busqueda)
            return [
                {
                    "enfermedad": record["enfermedad"],
                    "gravedad": record["gravedad"],
                    "score": round(record["score_final"], 2),
                }
                for record in result
            ]

    def obtener_ranking_con_intensidad(self, sintomas_json: list) -> list:
        """Top 3 enfermedades ponderando sensibilidad clínica por la intensidad declarada por el usuario."""
        query = """
        UNWIND $datos AS item
        MATCH (e:Enfermedad)-[rel:GENERA]->(s:Sintoma)
        WHERE toLower(s.nombre) = toLower(item.nombre)
        WITH e, sum(rel.probabilidad_presencia * item.intensidad) AS sensibilidad_ponderada
        RETURN e.nombre AS enfermedad,
               e.gravedad AS gravedad,
               (sensibilidad_ponderada * e.frecuencia) AS score_final
        ORDER BY score_final DESC
        LIMIT 3
        """
        with self.driver.session() as session:
            result = session.run(query, datos=sintomas_json)
            return [
                {
                    "enfermedad": record["enfermedad"],
                    "gravedad": record["gravedad"],
                    "score": round(record["score_final"], 2),
                }
                for record in result
            ]

