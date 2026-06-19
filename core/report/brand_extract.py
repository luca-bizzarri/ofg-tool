# -*- coding: utf-8 -*-
"""
Estrazione dell'identità visiva dal sito del cliente: colori principali, font e
(best effort) il logo. Serve a PRE-COMPILARE la palette del report, che poi
l'operatore conferma o corregge a mano. Niente è automatico e definitivo.

Strategia: scarica la home, raccoglie il CSS (inline + fogli collegati), conta i
colori esadecimali, scarta bianchi/neri/grigi per il primario/secondario, sceglie
il colore più presente e saturo come primario, un secondo distinto come secondario
e il più scuro ricorrente come colore scuro. I font vengono dai font-family.
"""
import base64
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; OFG-Report/1.0)"}
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")
_FONT = re.compile(r"font-family\s*:\s*([^;{}\"']+)", re.I)
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "inherit", "initial", "unset",
                  "system-ui", "-apple-system", "blinkmacsystemfont", "arial", "helvetica"}


def _get(url, timeout=10):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r


def _norm(h):
    h = h.lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(h):
    r, g, b = _rgb(h)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _sat(h):
    r, g, b = [x / 255.0 for x in _rgb(h)]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def _logo_data_uri(html, base_url):
    """Cerca un logo nel sito (apple-touch-icon / icon / og:image) e lo incorpora."""
    cands = re.findall(r'<link[^>]+rel=["\'][^"\']*(?:apple-touch-icon|icon)[^"\']*["\'][^>]*>', html, re.I)
    hrefs = []
    for tag in cands:
        m = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if m:
            hrefs.append(m.group(1))
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if og:
        hrefs.append(og.group(1))
    for href in hrefs:
        try:
            u = urljoin(base_url, href)
            r = _get(u)
            ct = r.headers.get("content-type", "image/png").split(";")[0]
            if "image" in ct and len(r.content) < 600_000:
                return "data:%s;base64,%s" % (ct, base64.b64encode(r.content).decode("ascii"))
        except Exception:
            continue
    return ""


def extract(url):
    """Ritorna {primary, secondary, dark, fonts:[...], logo, note}. Campi vuoti se non trovati."""
    out = {"primary": "", "secondary": "", "dark": "", "fonts": [], "logo": "", "note": ""}
    if not url:
        return out
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = _get(url)
        html = r.text
    except Exception as e:
        out["note"] = f"Sito non raggiungibile: {str(e)[:80]}"
        return out

    css = html
    # fogli di stile collegati (max 5)
    for href in re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)[:5]:
        try:
            css += "\n" + _get(urljoin(url, href)).text
        except Exception:
            pass

    # colori
    counts = Counter(_norm(h) for h in _HEX.findall(css))
    counts = {h: n for h, n in counts.items()}
    # candidati per primario/secondario: saturi e non troppo chiari/scuri
    cand = sorted(
        [(h, n) for h, n in counts.items() if _sat(h) >= 0.25 and 0.12 <= _lum(h) <= 0.9],
        key=lambda x: (x[1] * (0.5 + _sat(x[0]))), reverse=True)
    if cand:
        out["primary"] = cand[0][0]
        for h, _ in cand[1:]:
            if h != out["primary"]:
                out["secondary"] = h
                break
    # scuro: il più ricorrente tra i colori scuri (sennò #111111)
    darks = sorted([(h, n) for h, n in counts.items() if _lum(h) <= 0.22], key=lambda x: x[1], reverse=True)
    out["dark"] = darks[0][0] if darks else "#111111"
    if not out["secondary"]:
        out["secondary"] = out["primary"] or "#ff8a3d"
    if not out["primary"]:
        out["note"] = "Nessun colore di brand evidente trovato: imposta i colori a mano."

    # font
    fonts = []
    for fam in _FONT.findall(css):
        first = fam.split(",")[0].strip().strip("'\"")
        if first and first.lower() not in _GENERIC_FONTS and len(first) < 40 and first not in fonts:
            fonts.append(first)
    out["fonts"] = fonts[:5]

    out["logo"] = _logo_data_uri(html, url)
    return out
