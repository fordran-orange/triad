"""Product application endpoints; separate from protected Triad coordination."""

from fastapi import FastAPI

app = FastAPI(title="Triad product application")


@app.get("/health")
def health():
    return {"status": "ok"}
