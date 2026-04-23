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

if __name__ == "__main__":
    # --- ZONA DE PRUEBA ---
    URI = "bolt://localhost:7687"
    USER = "neo4j"
    PASSWORD = "tu_contraseña_aqui"

    db = MedicoDB(URI, USER, PASSWORD)

    # Prueba con una consulta Cypher real
    query = """
    MATCH (e:Enfermedad)-[:GENERA]->(s:Sintoma)
    WHERE toLower(e.nombre) CONTAINS toLower('Gastroenteritis')
    RETURN e.nombre AS enfermedad, e.gravedad AS gravedad, collect(s.nombre) AS sintomas
    """
    resultados = db.ejecutar_consulta(query)
    print(f"Resultados: {resultados}")
    db.close()