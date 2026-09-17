from neo4j import GraphDatabase
from triad.settings import ROOT, Settings


def main():
    settings = Settings()
    with GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value())
    ) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for statement in (
                (ROOT / "infrastructure/neo4j/001_constraints.cypher").read_text().split(";")
            ):
                if statement.strip():
                    session.run(statement).consume()
    print("Neo4j constraints applied")


if __name__ == "__main__":
    main()
