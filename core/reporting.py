"""
Standard unico per i report di OFG Tool.

Centralizza qui: (1) la struttura OBBLIGATORIA dei report (cosi' ogni report,
per ogni cliente e tipo, esce uguale), (2) la sanitizzazione del testo per i PDF
(evita i crash di fpdf con caratteri non latin-1), (3) il costruttore PDF unico.

Cambiando questo file cambi lo standard di TUTTI i report in un colpo solo.
"""
import base64
import html as _html
import os
import re
import time

import pandas as pd
from fpdf import FPDF


# --- Brand OFG (loghi, colori, font) -------------------------------------
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
_LOGO_BLACK = os.path.join(_ASSETS, "Logo_no payoff_nero.png")     # da usare su fondo BIANCO
_LOGO_NEG = os.path.join(_ASSETS, "Logo_no payoff_negativo.png")   # da usare su fondo NERO
YELLOW = (255, 255, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⬀-⯿⌀-⏿]",
    flags=re.UNICODE,
)


def _strip_emoji(text) -> str:
    """Rimuove le emoji (Raleway non le ha) mantenendo accenti, euro e tipografia."""
    return _EMOJI_RE.sub("", str(text if text is not None else ""))


def _register_brand_fonts(pdf) -> bool:
    """Registra il font aziendale Raleway nel PDF. Ritorna True se riuscito."""
    try:
        pdf.add_font("Raleway", "", os.path.join(_ASSETS, "Raleway-Regular.ttf"))
        pdf.add_font("Raleway", "B", os.path.join(_ASSETS, "Raleway-Bold.ttf"))
        pdf.add_font("Raleway", "I", os.path.join(_ASSETS, "Raleway-Italic.ttf"))
        return True
    except Exception:
        return False


# Caratteri non-latin-1 (em-dash, virgolette tipografiche, ellissi, euro, emoji)
# che fanno crashare i font core di fpdf: li convertiamo in equivalenti sicuri.
_PDF_REPLACEMENTS = {
    "—": "-", "–": "-", "‒": "-", "−": "-",
    "‘": "'", "’": "'", "‚": "'",
    "“": '"', "”": '"', "„": '"',
    "…": "...", "•": "-", "·": "-",
    " ": " ", " ": " ", " ": " ",
    "€": "EUR", "™": "(TM)", "®": "(R)", "­": "",
}


def sanitize_pdf_text(text) -> str:
    """Rende una stringa sicura per i font core di fpdf (latin-1).

    Sostituisce i simboli tipografici comuni e rimuove tutto cio' che non e'
    codificabile in latin-1 (es. emoji), evitando l'eccezione di fpdf.output().
    """
    if text is None:
        return ""
    s = str(text)
    for bad, good in _PDF_REPLACEMENTS.items():
        s = s.replace(bad, good)
    return s.encode("latin-1", "ignore").decode("latin-1")


def _norm_number(x) -> str:
    """Normalizza una stringa numerica con separatori IT/US e simboli valuta.
    Robusto a None / NaN / float in ingresso (celle vuote dei file reali)."""
    if x is None:
        return ""
    x = str(x).strip()
    if not x or x == "-" or x.lower() == "nan":
        return ""
    has_dot, has_comma = "." in x, "," in x
    if has_dot and has_comma:
        # l'ultimo separatore presente e' quello decimale
        if x.rfind(",") > x.rfind("."):
            return x.replace(".", "").replace(",", ".")   # 1.234,56 (IT)
        return x.replace(",", "")                          # 1,234.56 (US)
    if has_comma:
        dec = x.split(",")[-1]
        if len(dec) == 3 and x.count(",") == 1:
            return x.replace(",", "")                      # 1,000 -> 1000 (migliaia)
        return x.replace(",", ".")                         # 10,50 -> 10.50 (decimale)
    if has_dot:
        # Punto isolato: 3 cifre dopo l'ultimo punto = separatore migliaia
        # (2.000 -> 2000, 1.234.567 -> 1234567); altrimenti decimale (10.50, 1.71).
        if len(x.split(".")[-1]) == 3:
            return x.replace(".", "")
    return x


def to_numeric_series(series):
    """Converte una colonna pandas in numerico gestendo simboli valuta e
    separatori migliaia/decimali tipici degli export Meta/Google. I valori non
    convertibili diventano 0 (cosi' i calcoli non crashano sui file reali)."""
    s = series.fillna("").astype(str).str.replace(r"[^\d,.\-]", "", regex=True).map(_norm_number)
    return pd.to_numeric(s, errors="coerce").fillna(0)


def col_sum(df, col) -> float:
    """Somma robusta di una colonna (0 se la colonna non esiste)."""
    if not col or col not in df.columns:
        return 0.0
    return float(to_numeric_series(df[col]).sum())


def col_mean(df, col) -> float:
    """Media robusta di una colonna (0 se la colonna non esiste o e' vuota)."""
    if not col or col not in df.columns:
        return 0.0
    s = to_numeric_series(df[col])
    return float(s.mean()) if len(s) else 0.0


def build_standard_report_prompt(tipo, client_id, periodo, context, metriche_str, parametri, dati_sample) -> str:
    """Costruisce il prompt con la STRUTTURA STANDARD (uguale per ogni report).

    L'LLM deve produrre sempre le stesse 4 sezioni, cosi' tutti i report
    risultano uniformi. Il `context` (memoria del cliente) serve a personalizzare
    tono e raccomandazioni: e' la prova che i dati caricati vengono usati.
    """
    return (
        f"Sei un analista marketing senior. Scrivi un '{tipo}' professionale per il cliente '{client_id}'.\n\n"
        f"## DATI GREZZI (campione):\n{dati_sample}\n\n"
        f"## METRICHE AGGREGATE:\n{metriche_str}\n\n"
        f"## CONTESTO CLIENTE (dalla sua memoria - USALO per tono e raccomandazioni su misura):\n"
        f"{context or 'Nessun contesto disponibile.'}\n\n"
        f"## PARAMETRI: {parametri} | Periodo: {periodo}\n\n"
        f"## STRUTTURA OBBLIGATORIA (usa ESATTAMENTE queste 4 sezioni, in quest'ordine, "
        f"con questi titoli in MAIUSCOLO, per OGNI report):\n"
        f"EXECUTIVE SUMMARY\n(3 punti sintetici sui risultati chiave)\n\n"
        f"ANALISI PERFORMANCE\n(cosa ha funzionato e cosa no, citando i numeri reali)\n\n"
        f"RACCOMANDAZIONI\n(3-5 azioni concrete, numerate)\n\n"
        f"PROSSIMI PASSI\n(2-3 passi operativi per il prossimo periodo)\n\n"
        f"## REGOLE FERREE: usa SOLO i dati forniti e il contesto cliente. "
        f"Se un dato non c'e', scrivi [INFORMAZIONE MANCANTE]: NON inventare. "
        f"Scrivi un'analisi APPROFONDITA e professionale: 120-200 parole per sezione, "
        f"citando numeri concreti e collegandoli alle scelte strategiche (non frasi generiche). "
        f"Le RACCOMANDAZIONI devono essere azioni operative specifiche, non ovvieta'. "
        f"Solo testo semplice (niente markdown), con i 4 titoli di sezione in MAIUSCOLO."
    )


def build_standard_report_pdf(titolo, client_id, periodo, metriche, ai_text, fonti=None) -> bytes:
    """Genera il PDF nello STANDARD unico. Restituisce i byte del PDF.

    Layout fisso: Copertina -> 1. KPI Principali (tabella) -> 2. Analisi e
    Raccomandazioni (testo AI) -> Fonti di memoria utilizzate.
    Tutto il testo passa da sanitize_pdf_text: niente crash su caratteri strani.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    font_ok = _register_brand_fonts(pdf)
    FONT = "Raleway" if font_ok else "Helvetica"
    # Con il font unicode togliamo solo le emoji; col font core serve il latin-1.
    clean = _strip_emoji if font_ok else sanitize_pdf_text

    def section_title(testo):
        pdf.set_text_color(*BLACK)
        pdf.set_font(FONT, "B", 16)
        pdf.set_x(pdf.l_margin)
        pdf.cell(0, 10, clean(testo), ln=True)
        y = pdf.get_y()
        pdf.set_draw_color(*YELLOW)
        pdf.set_line_width(1.3)
        pdf.line(pdf.l_margin, y, pdf.l_margin + 55, y)
        pdf.ln(5)

    # ---------- COPERTINA (fondo NERO) ----------
    pdf.add_page()
    pdf.set_fill_color(*BLACK)
    pdf.rect(0, 0, 210, 297, "F")
    try:
        pdf.image(_LOGO_NEG, x=(210 - 85) / 2, y=42, w=85)
    except Exception:
        pass
    pdf.set_y(135)
    pdf.set_text_color(*YELLOW)
    pdf.set_font(FONT, "B", 26)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, 12, clean(titolo), align="C")
    pdf.ln(6)
    pdf.set_text_color(*WHITE)
    pdf.set_font(FONT, "B", 15)
    pdf.cell(0, 10, clean(f"Cliente: {client_id}"), ln=True, align="C")
    pdf.set_font(FONT, "", 13)
    pdf.cell(0, 9, clean(f"Periodo: {periodo}"), ln=True, align="C")
    pdf.set_y(-24)
    pdf.set_text_color(*WHITE)
    pdf.set_font(FONT, "I", 10)
    pdf.cell(0, 8, clean(f"Generato il {time.strftime('%d/%m/%Y')}"), ln=True, align="C")

    # ---------- PAGINE INTERNE (fondo BIANCO) ----------
    pdf.add_page()
    pdf.set_text_color(*BLACK)
    try:
        pdf.image(_LOGO_BLACK, x=pdf.l_margin, y=10, w=38)
    except Exception:
        pass
    pdf.ln(22)

    # 1. KPI Principali
    section_title("1. KPI Principali")
    pdf.set_font(FONT, "B", 12)
    pdf.set_fill_color(*YELLOW)
    pdf.set_text_color(*BLACK)
    pdf.cell(95, 10, clean("Metrica"), border=0, fill=True)
    pdf.cell(95, 10, clean("Valore"), border=0, fill=True, ln=True)
    pdf.set_font(FONT, "", 11)
    fill = False
    for k, v in (metriche or []):
        pdf.set_fill_color(245, 245, 245)
        pdf.set_x(pdf.l_margin)
        pdf.cell(95, 8, clean(str(k)), border=0, fill=fill)
        pdf.cell(95, 8, clean(str(v)), border=0, fill=fill, ln=True)
        fill = not fill

    # 2. Analisi e Raccomandazioni (testo AI con le 4 sezioni standard)
    pdf.ln(8)
    section_title("2. Analisi e Raccomandazioni")
    pdf.set_text_color(*BLACK)
    for line in clean(ai_text).split("\n"):
        t = line.replace("**", "").replace("*", "").replace("#", "").strip()
        if not t:
            continue
        is_head = t.isupper() and len(t) < 45
        pdf.set_font(FONT, "B" if is_head else "", 12 if is_head else 11)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6, t)
        if is_head:
            pdf.ln(1)

    # Fonti di memoria utilizzate (prova del grounding)
    if fonti:
        pdf.ln(6)
        pdf.set_font(FONT, "B", 11)
        pdf.set_text_color(*BLACK)
        pdf.set_x(pdf.l_margin)
        pdf.cell(0, 8, clean("Fonti di memoria utilizzate"), ln=True)
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(90, 90, 90)
        for f in list(fonti)[:15]:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, clean("- " + str(f)))

    return bytes(pdf.output())


# ============================================================
#  SLIDE HTML NAVIGABILI (export presentazione, stampabile in PDF dal browser)
# ============================================================

def _b64_img(path) -> str:
    """Codifica un'immagine in data-URI base64, per un HTML autoconsistente."""
    try:
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


_SECTION_HEADINGS = ["EXECUTIVE SUMMARY", "ANALISI PERFORMANCE", "RACCOMANDAZIONI", "PROSSIMI PASSI"]


def _parse_report_sections(ai_text):
    """Spezza il testo AI nelle 4 sezioni standard (una slide per sezione)."""
    text = str(ai_text or "").replace("**", "").replace("#", "")
    up = text.upper()
    found = []
    for h in _SECTION_HEADINGS:
        p = up.find(h)
        if p != -1:
            found.append((p, h))
    found.sort()
    if not found:
        return [("Analisi", text.strip())]
    out = []
    for n, (pos, h) in enumerate(found):
        start = pos + len(h)
        end = found[n + 1][0] if n + 1 < len(found) else len(text)
        out.append((h.title(), text[start:end].strip(" \n:-")))
    return out


def _split_long_paragraph(p, limit=320):
    """Spezza un paragrafo molto lungo per frase, cosi' non sfora la slide."""
    if len(p) <= limit:
        return [p]
    parts = re.split(r"(?<=[.!?])\s+", p)
    out, cur = [], ""
    for s in parts:
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur.strip())
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def _paginate(paras, budget=620):
    """Distribuisce i paragrafi su piu' "pagine" (slide) entro un budget di
    caratteri, cosi' i testi lunghi non escono dalla slide."""
    expanded = []
    for p in paras:
        expanded.extend(_split_long_paragraph(p))
    pages, cur, cur_len = [], [], 0
    for p in expanded:
        if cur and cur_len + len(p) > budget:
            pages.append(cur)
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p)
    if cur:
        pages.append(cur)
    return pages or [[]]


_SLIDES_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__ - __CLIENT__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;600;800;900&display=swap" rel="stylesheet">
<style>
  :root{ --yellow:#ffff00; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  html,body{ height:100%; font-family:'Raleway',sans-serif; background:#000; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .deck{ display:flex; overflow-x:auto; scroll-snap-type:x mandatory; height:100vh; scroll-behavior:smooth; }
  .deck::-webkit-scrollbar{ display:none; }
  .slide{ min-width:100vw; height:100vh; scroll-snap-align:start; position:relative; display:flex; flex-direction:column; justify-content:center; padding:8vh 10vw; }
  .slide.cover{ background:#000; color:#fff; align-items:center; text-align:center; }
  .slide.cover img.logo{ width:min(360px,55vw); margin-bottom:6vh; }
  .slide.cover h1{ color:var(--yellow); font-weight:900; font-size:clamp(28px,5vw,56px); line-height:1.12; }
  .slide.cover .meta{ margin-top:4vh; font-size:clamp(16px,2vw,22px); font-weight:400; }
  .slide.cover .meta b{ font-weight:800; }
  .slide.cover .data{ position:absolute; bottom:5vh; font-size:14px; opacity:.7; font-style:italic; }
  .slide.light{ background:#fff; color:#111; }
  .slide.light .logo-sm{ position:absolute; top:5vh; left:10vw; width:120px; }
  .slide.light h2{ font-weight:900; font-size:clamp(24px,3.4vw,40px); text-transform:uppercase; margin-bottom:3vh; position:relative; padding-bottom:14px; }
  .slide.light h2:after{ content:''; position:absolute; left:0; bottom:0; width:70px; height:6px; background:var(--yellow); }
  .slide.light .body p{ font-size:clamp(15px,1.6vw,20px); line-height:1.55; margin-bottom:1.1em; max-width:62ch; font-weight:400; }
  .kpis{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:18px; margin-top:2vh; }
  .kpi{ background:#f4f4f4; border-top:6px solid var(--yellow); border-radius:10px; padding:22px 18px; text-align:center; }
  .kpi-v{ color:#111; font-weight:900; font-size:clamp(20px,2.6vw,34px); }
  .kpi-k{ color:#555; font-weight:600; font-size:12px; margin-top:8px; text-transform:uppercase; letter-spacing:.5px; }
  .fonti{ list-style:none; } .fonti li{ padding:8px 0; border-bottom:1px solid #eee; font-size:16px; }
  .small{ margin-top:3vh; font-size:14px; color:#666; font-style:italic; }
  .nav{ position:fixed; bottom:24px; right:24px; display:flex; gap:10px; z-index:10; }
  .nav button{ width:46px; height:46px; border:none; border-radius:50%; background:#000; color:var(--yellow); font-size:20px; cursor:pointer; box-shadow:0 4px 14px rgba(0,0,0,.25); }
  .nav button:hover{ background:var(--yellow); color:#000; }
  .dots{ position:fixed; bottom:32px; left:50%; transform:translateX(-50%); display:flex; gap:8px; z-index:10; }
  .dots i{ width:9px; height:9px; border-radius:50%; background:rgba(0,0,0,.25); cursor:pointer; transition:.2s; }
  .dots i.on{ background:var(--yellow); width:26px; border-radius:6px; }
  .hint{ position:fixed; top:18px; right:22px; font-size:12px; color:#999; z-index:10; }
  @media print{
    @page{ size:A4 landscape; margin:0; }
    html,body{ background:#fff; }
    .deck{ display:block; overflow:visible; height:auto; }
    .slide{ width:100%; height:100vh; page-break-after:always; scroll-snap-align:none; }
    .nav,.dots,.hint{ display:none !important; }
  }
</style>
</head>
<body>
<div class="hint">PDF: Ctrl/Cmd + P (attiva "Grafica di sfondo")</div>
<div class="deck" id="deck">
  <section class="slide cover">
    <img class="logo" src="__LOGONEG__" alt="OFG"/>
    <h1>__TITLE__</h1>
    <div class="meta"><b>__CLIENT__</b><br/>__PERIODO__</div>
    <div class="data">Generato il __DATA__</div>
  </section>
  <section class="slide light">
    <img class="logo-sm" src="__LOGOBLACK__" alt="logo"/>
    <div class="content"><h2>KPI Principali</h2><div class="kpis">__KPI__</div></div>
  </section>
  __SECTIONS__
</div>
<div class="dots" id="dots"></div>
<div class="nav"><button onclick="go(idx-1)">&#8249;</button><button onclick="go(idx+1)">&#8250;</button></div>
<script>
  const deck=document.getElementById('deck');
  const slides=[...deck.querySelectorAll('.slide')];
  const dots=document.getElementById('dots');
  let idx=0;
  slides.forEach((s,n)=>{ const d=document.createElement('i'); d.onclick=()=>go(n); dots.appendChild(d); });
  function mark(){ [...dots.children].forEach((d,n)=>d.classList.toggle('on',n===idx)); }
  function go(n){ idx=Math.max(0,Math.min(slides.length-1,n)); slides[idx].scrollIntoView({behavior:'smooth',inline:'start'}); mark(); }
  deck.addEventListener('scroll',()=>{ idx=Math.round(deck.scrollLeft/window.innerWidth); mark(); });
  document.addEventListener('keydown',e=>{ if(e.key==='ArrowRight'||e.key===' ')go(idx+1); if(e.key==='ArrowLeft')go(idx-1); });
  mark();
</script>
</body>
</html>"""


def build_report_slides_html(titolo, client_id, periodo, metriche, ai_text, fonti=None) -> str:
    """Genera un deck di slide HTML brandizzato, autoconsistente e navigabile
    (stampabile in PDF dal browser). Copertina nera + logo negativo, slide
    bianche con logo nero, accenti gialli, font Raleway."""
    logo_neg = _b64_img(_LOGO_NEG)
    logo_black = _b64_img(_LOGO_BLACK)

    kpi_cards = "".join(
        f'<div class="kpi"><div class="kpi-v">{_esc(v)}</div><div class="kpi-k">{_esc(k)}</div></div>'
        for k, v in (metriche or [])
    )

    sections_html = ""
    for titolo_sez, body in _parse_report_sections(ai_text):
        paras = [p.strip() for p in body.split("\n") if p.strip()]
        pages = _paginate(paras)
        for pi, chunk in enumerate(pages):
            suffix = f" ({pi + 1}/{len(pages)})" if len(pages) > 1 else ""
            body_html = "".join(f"<p>{_esc(p)}</p>" for p in chunk) or "<p>[INFORMAZIONE MANCANTE]</p>"
            sections_html += (
                '<section class="slide light">'
                f'<img class="logo-sm" src="{logo_black}" alt="logo"/>'
                f'<div class="content"><h2>{_esc(titolo_sez + suffix)}</h2><div class="body">{body_html}</div></div>'
                '</section>'
            )

    # (La slide "Fonti di memoria" e' stata rimossa su richiesta: la prova del
    # grounding resta visibile nell'app come caption, non nel deck per il cliente.)

    doc = _SLIDES_TEMPLATE
    for token, value in [
        ("__TITLE__", _esc(titolo)),
        ("__CLIENT__", _esc(client_id)),
        ("__PERIODO__", _esc(periodo)),
        ("__DATA__", _esc(time.strftime("%d/%m/%Y"))),
        ("__LOGONEG__", logo_neg),
        ("__LOGOBLACK__", logo_black),
        ("__KPI__", kpi_cards),
        ("__SECTIONS__", sections_html),
    ]:
        doc = doc.replace(token, value)
    return doc
