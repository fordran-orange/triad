"""Local baseline archive and PostgreSQL restore verification; never exports secrets."""
import hashlib
import json
import subprocess
import zipfile

from psycopg import sql
from triad.settings import ROOT
from triad.store import Store


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def main():
    target = ROOT / "data/temp/pre-split-baseline"
    target.mkdir(parents=True, exist_ok=True)
    dump = run("docker", "exec", "triad-postgres-1", "sh", "-c",
               'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc').stdout
    (target / "postgres.dump").write_bytes(dump)
    restore_db = "core_baseline_restore"
    store = Store()
    with store.connect() as conn:
        conn.autocommit = True
        if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (restore_db,)).fetchone():
            raise RuntimeError("Restore database already exists; retain it for inspection")
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_db)))
    restored = Store(store.settings.model_copy(update={"postgres_db": restore_db}))
    with restored.connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        conn.execute("SELECT timescaledb_pre_restore()")
    run("docker", "exec", "-i", "triad-postgres-1", "sh", "-c",
        'pg_restore -U "$POSTGRES_USER" -d core_baseline_restore --exit-on-error', input=dump)
    with restored.connect() as conn:
        conn.execute("SELECT timescaledb_post_restore()")
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='triad'").fetchall()
        counts = {r['tablename']: conn.execute(sql.SQL('SELECT count(*) AS n FROM triad.{}').format(sql.Identifier(r['tablename']))).fetchone()['n'] for r in tables}
    manifest = {}
    with zipfile.ZipFile(target / "artifacts.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in ("data/raw", "data/canonical", "data/derived", "data/manifests", "research/experiments", "research/generated", "docs/vault"):
            for path in sorted((ROOT / folder).rglob('*')):
                if path.is_file() and '.obsidian' not in path.parts:
                    relative = path.relative_to(ROOT).as_posix()
                    archive.write(path, relative)
                    manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(target / "artifacts.zip") as archive:
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        archive.extractall(target / "restored-artifacts")
    report = {"postgres_restore_database": restore_db, "postgres_counts": counts,
              "artifacts": manifest, "postgres_sha256": hashlib.sha256(dump).hexdigest()}
    (target / "manifest.json").write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({"backup": str(target), "restored_tables": len(counts), "verified_artifacts": len(manifest)}))


if __name__ == '__main__':
    main()
