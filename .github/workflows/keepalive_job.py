import os

def run_keepalive():
    # Obtener variables desde el entorno del sistema
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    neo4j_uri = os.environ.get('NEO4J_URI')
    neo4j_username = os.environ.get('NEO4J_USERNAME')
    neo4j_password = os.environ.get('NEO4J_PASSWORD')
    keepalive_query = os.environ.get('KEEPALIVE_QUERY')

    # Validación de seguridad: Verificar que existan antes de proceder
    secrets = [gemini_api_key, neo4j_uri, neo4j_username, neo4j_password, keepalive_query]
    if any(secret is None for secret in secrets):
        print("Error: Uno o más secretos no fueron encontrados en el entorno.")
        return

    print("Conectando a la base de datos y ejecutando query...")
    # Aquí iría el resto de tu lógica de conexión...

if __name__ == "__main__":
    run_keepalive()
