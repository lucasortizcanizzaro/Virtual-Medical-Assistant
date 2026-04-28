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

