"""Add lineage metadata without changing historical IDs, links or artifact contents."""
from trading_core.brain import Brain
from trading_core.store import Store


def main():
    store=Store()
    with store.connect() as conn:
        rows=[]
        for table in ('work_items','orchestration_records','day3_records'):
            rows.extend(conn.execute(f'SELECT id,owner FROM core.{table}').fetchall())
    with Brain(store).driver() as driver, driver.session() as session:
        session.run("MATCH (n) WHERE n.owner IS NULL SET n.owner='triad'").consume()
        session.run("MATCH (n:Agent) SET n.owner='core'").consume()
        session.run('UNWIND $rows AS row MATCH (n {id:row.id}) SET n.owner=row.owner', rows=rows).consume()
        result=session.run('MATCH (n) RETURN n.owner AS owner,count(n) AS nodes').data()
    print(result)


if __name__=='__main__':main()
