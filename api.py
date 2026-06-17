"""
api.py — Micro-servizio HTTP per lo SLIDE-BUILDER (OFG).

Espone un endpoint che genera il MARKDOWN OFG di una presentazione a partire
da un brief e/o testo libero. Riusa la logica condivisa in core/slides.py
(stesso prompt usato anche dalla pagina "Slide" dell'app Streamlit) e l'LLM
gia' configurato dell'app (OpenRouter). NON tocca l'app Streamlit.

Avvio (separato da Streamlit, porta 8800):
    cd C:\\ai\\ofg\\ofg-tool
    uvicorn api:app --host 127.0.0.1 --port 8800

NB: e' un backend headless. NON compare nell'interfaccia Streamlit e NON viene
eseguito da Streamlit Cloud (che avvia solo `streamlit run app/Home.py`). La
stessa generazione e' disponibile dentro Streamlit nella pagina "Slide".
"""
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import config
from core import slides

app = FastAPI(title="OFG Slide Composer", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ImageRef(BaseModel):
    id: str
    name: str = ""


class ComposeRequest(BaseModel):
    brief: Optional[str] = ""
    text: Optional[str] = ""
    images: List[ImageRef] = []
    client_id: Optional[str] = None
    max_slides: int = 12


@app.get("/health")
def health():
    # Leggero: non importa rag_engine (che inizializza Qdrant).
    return {"status": "ok", "model": config.MODEL_NAME}


@app.post("/compose")
def compose(req: ComposeRequest):
    try:
        return slides.compose(
            brief=req.brief or "",
            text=req.text or "",
            images=[i.model_dump() for i in req.images],
            client_id=req.client_id,
            max_slides=req.max_slides,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "Generazione fallita: %s" % e})
