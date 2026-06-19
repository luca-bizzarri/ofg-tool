# -*- coding: utf-8 -*-
"""
Renderer del report: prende i dati normalizzati (DATA) e il brand del cliente
(colori + logo) e produce un singolo file HTML autoconsistente, identico nella
forma al report di riferimento ma con dati, logo e colori del cliente.

Uso tipico:
    from core.report import render
    html = render.render_report(data, brand)   # -> stringa HTML completa

`data`  : dict con la struttura DATA (vedi sample_instagram.json).
`brand` : dict con 'primary', 'secondary', 'dark' (colori esadecimali) e
          'logo' (data-URI dell'immagine, vedi img_to_data_uri).
"""
import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_report.html")  # shell multi canale

# Brand di default (riproduce la palette del report di esempio GESA).
DEFAULT_BRAND = {
    "primary": "#e9501c",
    "secondary": "#ff8a3d",
    "dark": "#111111",
    "logo": "",
}

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp"}


def img_to_data_uri(path: str) -> str:
    """Converte un'immagine su disco in data-URI base64 (per logo autoconsistente)."""
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    mime = _MIME.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def load_template() -> str:
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        return f.read()


def load_sample() -> dict:
    """Dati di esempio (Instagram) per provare il renderer senza parsing."""
    with open(os.path.join(HERE, "sample_instagram.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def bytes_to_data_uri(raw: bytes, filename: str = "logo.png") -> str:
    """Converte i byte di un'immagine (es. upload Streamlit) in data-URI base64."""
    if not raw:
        return ""
    ext = os.path.splitext(filename or "")[1].lower()
    mime = _MIME.get(ext, "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _title(report: dict) -> str:
    meta = report.get("meta", {}) if isinstance(report, dict) else {}
    brand = meta.get("brand", "Report")
    period = meta.get("period", "")
    return f"{brand} | {period}".strip(" |") if period else brand


def to_report(data: dict) -> dict:
    """Normalizza l'input nella forma multi canale {meta, channels:[...]}.

    Accetta sia un report gia' multi canale, sia un singolo canale (output del
    parser o sample): in quel caso lo avvolge in channels=[...]."""
    if isinstance(data, dict) and "channels" in data:
        return data
    meta = dict(data.get("meta") or {})
    ch = dict(data)
    ch.setdefault("id", (meta.get("channel") or "instagram").lower())
    ch.setdefault("label", meta.get("channel", "Instagram"))
    ch.setdefault("type", "instagram")
    return {"meta": meta, "channels": [ch]}


def render_report(data: dict, brand: dict = None, title: str = None) -> str:
    """Inietta dati, colori e logo nel template e ritorna l'HTML completo."""
    report = to_report(data)
    b = dict(DEFAULT_BRAND)
    if brand:
        b.update({k: v for k, v in brand.items() if v})
    html = load_template()
    html = html.replace("{{DATA}}", json.dumps(report, ensure_ascii=False))
    html = html.replace("{{PRIMARY}}", b["primary"])
    html = html.replace("{{SECONDARY}}", b["secondary"])
    html = html.replace("{{DARK}}", b["dark"])
    html = html.replace("{{LOGO}}", b.get("logo", ""))
    html = html.replace("{{TITLE}}", title or _title(report))
    return html
