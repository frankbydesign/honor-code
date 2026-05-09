from fastapi import FastAPI

app = FastAPI(title="Honor Code API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
