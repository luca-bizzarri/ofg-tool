# -*- coding: utf-8 -*-
"""
Builder una-tantum: trasforma il report GESA di esempio in un TEMPLATE
riutilizzabile e brandizzabile.

Cosa fa:
1. Estrae l'oggetto `DATA` (il JSON che guida tutto il report) e lo salva come
   campione (sample_instagram.json), utile per i test del renderer.
2. Rende parametrici i colori di brand: i colori accento vengono spostati su
   variabili CSS e i valori in :root diventano segnaposto ({{PRIMARY}}, ...).
3. Rende parametrico il logo (le immagini base64 -> {{LOGO}}), il titolo
   ({{TITLE}}) e i dati ({{DATA}}).

Il risultato (template_instagram.html) NON contiene piu' dati o brand di GESA:
quelli li inietta `render.py` per ogni cliente.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # core/report -> core -> ofg-tool
SRC = os.path.join(ROOT, "gesa_instagram_report_maggio_2026_con_logo_brand.html")
TEMPLATE_OUT = os.path.join(HERE, "template_instagram.html")
SAMPLE_OUT = os.path.join(HERE, "sample_instagram.json")


def build():
    with open(SRC, "r", encoding="utf-8") as f:
        html = f.read()
    orig_len = len(html)
    report = []

    # --- 1) Estrai e rimpiazza l'oggetto DATA (riga singola "const DATA = {...};") ---
    lines = html.split("\n")
    data_json = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("const DATA = ") and s.endswith(";"):
            data_json = s[len("const DATA = "):].rstrip(";").strip()
            indent = ln[: len(ln) - len(ln.lstrip())]
            lines[i] = indent + "const DATA = {{DATA}};"
            break
    if data_json is None:
        raise SystemExit("ERRORE: riga 'const DATA = ...' non trovata.")
    html = "\n".join(lines)
    parsed = json.loads(data_json)  # valida che sia JSON corretto
    with open(SAMPLE_OUT, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    report.append(f"DATA estratto: {len(data_json)} char, chiavi top-level: {sorted(parsed.keys())}")

    # --- 2) Brand: prima i valori in :root diventano segnaposto ---
    root_subs = [
        ("    --purple: #e9501c;", "    --purple: {{PRIMARY}};"),
        ("    --orange: #ff8a3d;", "    --orange: {{SECONDARY}};"),
        ("    --navy: #111111;", "    --navy: {{DARK}};"),
        ("    --pink: #1f1f1f;", "    --pink: {{DARK}};"),
    ]
    for old, new in root_subs:
        n = html.count(old)
        if n != 1:
            report.append(f"ATTENZIONE: '{old.strip()}' trovato {n} volte (atteso 1)")
        html = html.replace(old, new)

    # --- 3) Sweep degli stessi colori hardcoded altrove -> variabili CSS ---
    # (cosi' gradienti, barre e accenti seguono il brand del cliente)
    hex_sweep = [
        ("#e9501c", "var(--purple)"),
        ("#ff8a3d", "var(--orange)"),
        ("#1f1f1f", "var(--pink)"),
    ]
    for hx, var in hex_sweep:
        n = html.count(hx)
        html = html.replace(hx, var)
        report.append(f"sweep {hx} -> {var}: {n} occorrenze")
    # nota: #111111 (quasi-nero) resta come ancora neutra, valida per ogni brand

    # --- 4) Logo: le immagini base64 diventano {{LOGO}} ---
    logos = re.findall(r"data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+", html)
    report.append(f"loghi base64 trovati: {len(logos)} (lunghezze: {[len(x) for x in logos]})")
    html = re.sub(r"data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+", "{{LOGO}}", html)

    # --- 5) Titolo ---
    html = re.sub(r"<title>.*?</title>", "<title>{{TITLE}}</title>", html, count=1, flags=re.DOTALL)

    with open(TEMPLATE_OUT, "w", encoding="utf-8") as f:
        f.write(html)

    report.append(f"template scritto: {TEMPLATE_OUT} ({len(html)} char, da {orig_len})")
    report.append("segnaposto presenti: " + ", ".join(
        p for p in ["{{DATA}}", "{{PRIMARY}}", "{{SECONDARY}}", "{{DARK}}", "{{LOGO}}", "{{TITLE}}"]
        if p in html))
    print("\n".join(report))


if __name__ == "__main__":
    build()
