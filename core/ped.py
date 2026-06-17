"""
Motore PED (Piano Editoriale) di OFG Tool.

Due modalita':
1) generate_content(): genera UN contenuto strutturato (post/carosello/reel/stories)
   secondo le istruzioni (caption x3, hook virali, struttura carosello, script reel,
   set stories...), ancorato alla scheda cliente e alla rubrica scelta.
2) generate_calendar() + export_excel(): genera un CALENDARIO mensile dalle rubriche
   attivate e lo esporta in Excel nel formato del cliente.
"""
import io
import json
import re

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from core import rag_engine as rag
from core import clients


# "Di cosa hai bisogno" per tipologia di contenuto (istruzioni docx)
NEEDS = {
    "post": ["Caption social (3 versioni)", "Hook virale", "Head + Subhead visual", "Set stories a supporto"],
    "carousel": ["Caption social (3 versioni)", "Hook virale", "Struttura carosello (tavole)", "Set stories a supporto"],
    "reel": ["Script video", "Testi overlay", "Caption social (3 versioni)", "Hook virale (cover)", "Set stories a supporto"],
    "stories": ["Set 4 stories engage", "Set 4 stories conversion", "Set 4 stories interazione community"],
}

HOOK_TYPES = "Problem Hook, Curiosity Hook, Bold Claim Hook, Relatable Hook"
CAROUSEL_SEQ = "hook, setup, tension, insight, the shift, proof, soft cta, hard cta"

# Colonne del file PED (ordine esatto del formato Maniac Line / agenzia)
PED_COLUMNS = [
    "Week", "Date", "Post Type", "Content Type", "Format", "Social Channel",
    "Copy OUT Italian", "Copy OUT English", "CTA", "Content / Copy IN",
    "Stories", "ADV FB (5 post)", "ADV IG (9 post)", "Commenti e correzioni", "Status",
]


def _client_context(client_id, rubrica_nome=""):
    q = f"tono di voce, brand, posizionamento, regole, esempi di copy, {rubrica_nome}"
    res = rag.get_client_context(client_id, q, k=12)
    return res.get("context", ""), res.get("metadata", {}).get("sources", [])


def _lang_instruction(languages):
    if "EN" in (languages or []):
        return "Fornisci il copy in ITALIANO e, separatamente, la versione in INGLESE."
    return "Fornisci il copy solo in ITALIANO."


def generate_content(client_id, rubrica, content_type, obiettivo, piattaforme, prodotto, needs, languages, extra=""):
    """Genera UN contenuto strutturato. Ritorna testo (markdown) pronto da rivedere."""
    context, fonti = _client_context(client_id, rubrica.get("nome", ""))
    blacklist = rag.extract_constraints(client_id)
    tipologia = (content_type or "post").lower()

    # Istruzioni di output specifiche per tipologia
    out_rules = []
    if "Caption social (3 versioni)" in needs:
        out_rules.append("CAPTION SOCIAL: 3 versioni diverse (non variazioni della stessa frase).")
    if any("Hook virale" in n for n in needs):
        out_rules.append(f"HOOK VIRALE: una proposta per ciascun tipo ({HOOK_TYPES}).")
    if "Head + Subhead visual" in needs:
        out_rules.append("HEAD + SUBHEAD VISUAL: titolo e sottotitolo per il visual.")
    if "Struttura carosello (tavole)" in needs:
        out_rules.append(f"STRUTTURA CAROSELLO: una tavola per ogni step nella sequenza: {CAROUSEL_SEQ}.")
    if "Script video" in needs:
        out_rules.append("SCRIPT VIDEO: script parlato del reel con indicazione dei momenti.")
    if "Testi overlay" in needs:
        out_rules.append("TESTI OVERLAY: testi a schermo per il reel, in sequenza.")
    if any("Set stories" in n or "set" in n.lower() and "stor" in n.lower() for n in needs):
        sset = [n for n in needs if "stor" in n.lower()]
        out_rules.append("STORIES: " + "; ".join(sset))

    prompt = (
        f"Sei un Content & Creative Strategist senior. Crea il contenuto richiesto, coerente al 100% con "
        f"il tono di voce e i dati del cliente.\n\n"
        f"## CONTESTO CLIENTE (BASE ASSOLUTA - usa SOLO queste info, non inventare):\n{context or 'Nessun contesto.'}\n\n"
        f"## RUBRICA: {rubrica.get('nome','(libera)')}\n"
        f"Descrizione rubrica: {rubrica.get('descrizione','-')}\n"
        f"Taglio/angolo: {rubrica.get('taglio','-')}\n"
        f"Esempi rubrica: {rubrica.get('esempi','-')}\n\n"
        f"## BRIEF: Tipologia={tipologia} | Obiettivo={obiettivo} | Piattaforme={', '.join(piattaforme)} | Prodotto/Tema={prodotto or '-'}\n"
        f"Note extra: {extra or '-'}\n\n"
        f"## COSA PRODURRE:\n- " + "\n- ".join(out_rules or ["Contenuto completo nello stile del brand."]) + "\n\n"
        f"## REGOLE: {_lang_instruction(languages)} "
        f"NON usare MAI queste parole/frasi vietate: {', '.join(blacklist) if blacklist else 'nessuna'}. "
        f"Niente placeholder o frasi generiche: testi PRONTI alla pubblicazione. "
        f"Organizza l'output con titoli di sezione chiari in MAIUSCOLO."
    )
    return rag.llm.invoke(prompt).content, fonti


def _parse_json_array(raw):
    clean = (raw or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    m = re.search(r"(\[.*\])", clean, re.DOTALL)
    if m:
        clean = m.group(1)
    clean = re.sub(r",\s*([\]}])", r"\1", clean)
    try:
        data = json.loads(clean)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def generate_calendar(client_id, rubriche_attive, mese, anno, n_contenuti, channel, languages, extra=""):
    """Genera le righe del calendario mensile usando le rubriche attivate.

    Ritorna lista di dict-riga. Generazione a batch per robustezza.
    """
    context, fonti = _client_context(client_id)
    blacklist = rag.extract_constraints(client_id)
    rub_desc = "\n".join(
        f"- {r.get('nome')}: {r.get('descrizione','')} | taglio: {r.get('taglio','')} | tipologia tipica: {r.get('tipologia','')}"
        for r in rubriche_attive
    )
    lang_fields = '"copy_it":"...", "copy_en":"..."' if "EN" in (languages or []) else '"copy_it":"..."'

    rows = []
    batch = 3
    fatti = 0
    n_contenuti = max(1, min(int(n_contenuti), 40))
    while fatti < n_contenuti:
        q = min(batch, n_contenuti - fatti)
        prompt = (
            f"Sei un Content Strategist. Genera ESATTAMENTE {q} contenuti per il PIANO EDITORIALE di "
            f"{mese} {anno}, in JSON STRICT (array).\n\n"
            f"## CONTESTO CLIENTE (base assoluta, non inventare):\n{context or 'Nessun contesto.'}\n\n"
            f"## RUBRICHE ATTIVE (usa SOLO queste, a rotazione):\n{rub_desc}\n\n"
            f"## CANALE: {channel}\n"
            f"## FORMATO JSON di ogni contenuto:\n"
            f'{{"data":"YYYY-MM-DD","post_type":"reel|post|carousel|stories","content_type":"Product|Engage|Education|Brand|Event|Holidays",'
            f'"format":"NOME RUBRICA","channel":"{channel}",{lang_fields},"cta":"...","content_in":"brief/idea contenuto","stories":"eventuale set stories"}}\n\n'
            f"## REGOLE: date dentro {mese} {anno}, distribuite. {_lang_instruction(languages)} "
            f"Vietate (mai usarle): {', '.join(blacklist) if blacklist else 'nessuna'}. "
            f"Copy pronti alla pubblicazione, nello stile del brand. Note: {extra or '-'}. "
            f"Rispondi SOLO col JSON array valido."
        )
        data = _parse_json_array(rag.llm.invoke(prompt).content)
        rows.extend([d for d in data if isinstance(d, dict)])
        got = len([d for d in data if isinstance(d, dict)])
        fatti += got if got else q  # evita loop infinito se il batch fallisce
    return rows[:n_contenuti], fonti


def _week_label(date_str):
    """Da 'YYYY-MM-DD' a un'etichetta settimana semplice (giorno-based)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(date_str or ""))
    if not m:
        return ""
    day = int(m.group(3))
    start = ((day - 1) // 7) * 7 + 1
    return f"{start}-{start+6}"


def export_excel(rows, mese, languages):
    """Esporta le righe in un .xlsx nel formato PED. Ritorna i byte."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (mese or "PED")[:31]

    header_fill = PatternFill(start_color="111111", end_color="111111", fill_type="solid")
    header_font = Font(bold=True, color="FFFF00")
    for ci, col in enumerate(PED_COLUMNS, start=1):
        c = ws.cell(row=1, column=ci, value=col)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(vertical="center")

    for ri, r in enumerate(rows, start=2):
        ws.cell(row=ri, column=1, value=_week_label(r.get("data")))
        ws.cell(row=ri, column=2, value=str(r.get("data", "")))
        ws.cell(row=ri, column=3, value=r.get("post_type", ""))
        ws.cell(row=ri, column=4, value=r.get("content_type", ""))
        ws.cell(row=ri, column=5, value=r.get("format", ""))
        ws.cell(row=ri, column=6, value=r.get("channel", ""))
        ws.cell(row=ri, column=7, value=r.get("copy_it", ""))
        ws.cell(row=ri, column=8, value=r.get("copy_en", "") if "EN" in (languages or []) else "")
        ws.cell(row=ri, column=9, value=r.get("cta", ""))
        ws.cell(row=ri, column=10, value=r.get("content_in", ""))
        ws.cell(row=ri, column=11, value=r.get("stories", ""))
        ws.cell(row=ri, column=15, value="Da approvare")

    # larghezze e a-capo per le colonne di copy
    widths = {1: 14, 2: 12, 3: 11, 4: 13, 5: 22, 6: 18, 7: 55, 8: 55, 9: 18, 10: 40, 11: 40, 15: 14}
    for ci, w in widths.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
