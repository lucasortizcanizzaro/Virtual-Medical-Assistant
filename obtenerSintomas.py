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

