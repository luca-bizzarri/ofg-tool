"""
Scheda cliente (profilo) di OFG Tool.

Ogni cliente ha un PROFILO strutturato salvato nel registro Qdrant:
- languages: lingue del copy (["IT"] oppure ["IT", "EN"])
- rubriche: lista di rubriche/format del cliente, ognuna con nome, descrizione,
  taglio/obiettivo tipico, tipologia di contenuto tipica ed esempi.
- channels: piattaforme social abituali del cliente.

Le rubriche sono il cuore del PED: la generazione pesca qui (NON sono hardcoded
per un cliente specifico, valgono per qualsiasi cliente).
"""
import json
import uuid

from qdrant_client.http.models import PointStruct

from core import rag_engine as rag


DEFAULT_PROFILE = {
    "languages": ["IT"],
    "channels": ["Instagram", "Facebook"],
    "rubriche": [],   # [{nome, descrizione, taglio, tipologia, esempi}]
}

# Valori di riferimento (generici, validi per ogni cliente) usati nelle UI.
CONTENT_TYPES = ["Product", "Engage", "Education", "Brand", "Event", "Holidays"]
POST_TYPES = ["post", "carousel", "reel", "stories"]
OBJECTIVES = ["Awareness", "Engagement", "Consideration", "Conversion", "Education"]
CHANNELS = ["Instagram", "Facebook", "TikTok", "LinkedIn", "YouTube"]


def _pid(client_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, rag._clean_id(client_id)))


def get_profile(client_id: str) -> dict:
    """Ritorna il profilo del cliente (con default se assente)."""
    base = {
        "languages": list(DEFAULT_PROFILE["languages"]),
        "channels": list(DEFAULT_PROFILE["channels"]),
        "rubriche": [],
    }
    try:
        recs = rag.client.retrieve(
            collection_name=rag.collection_registry, ids=[_pid(client_id)], with_payload=True
        )
        if recs and recs[0].payload:
            prof = recs[0].payload.get("profile")
            if prof:
                data = json.loads(prof) if isinstance(prof, str) else prof
                base.update({k: data.get(k, base[k]) for k in base})
    except Exception:
        pass
    return base


def save_profile(client_id: str, profile: dict) -> bool:
    """Salva (upsert) il profilo del cliente nel registro."""
    cid = rag._clean_id(client_id)
    clean = {
        "languages": profile.get("languages") or ["IT"],
        "channels": profile.get("channels") or [],
        "rubriche": profile.get("rubriche") or [],
    }
    point = PointStruct(
        id=_pid(cid),
        vector=[0.1, 0.1, 0.1, 0.1],
        payload={"client_id": cid, "profile": json.dumps(clean, ensure_ascii=False)},
    )
    try:
        rag.client.upsert(collection_name=rag.collection_registry, points=[point])
        return True
    except Exception:
        return False


# --- Helper rubriche -----------------------------------------------------

def new_rubrica(nome="", descrizione="", taglio="", tipologia="reel", esempi="") -> dict:
    return {
        "nome": nome,
        "descrizione": descrizione,
        "taglio": taglio,            # obiettivo/angolo tipico della rubrica
        "tipologia": tipologia,      # post/carousel/reel/stories tipica
        "esempi": esempi,            # esempi di copy/contenuti della rubrica
    }


def get_rubriche(client_id: str) -> list:
    return get_profile(client_id).get("rubriche", [])


def rubrica_by_name(client_id: str, nome: str) -> dict:
    for r in get_rubriche(client_id):
        if r.get("nome", "").strip().lower() == (nome or "").strip().lower():
            return r
    return {}


def upsert_rubriche(client_id: str, rubriche: list) -> bool:
    prof = get_profile(client_id)
    prof["rubriche"] = rubriche
    return save_profile(client_id, prof)
