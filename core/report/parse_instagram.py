# -*- coding: utf-8 -*-
"""
Parser del report Instagram esportato da Agorapulse (PDF testuale).

Estrae in modo DETERMINISTICO (nessuna AI sui numeri, cosi' non si inventa
nulla) i dati nella struttura `DATA` usata dal template del report.

Cosa NON e' affidabile dal solo testo del PDF e finisce in `missing_data`
(verra' completato a mano nello step di revisione o dall'export dedicato):
- distribuzione follower per citta' (nel PDF e' solo un grafico),
- demografia esatta per eta'/genere (solo grafico),
- heatmap timing (solo grafico),
- testi narrativi e roadmap (li genera il motore di tono).
"""
import re

import PyPDF2

EN_MONTHS = {
    "january": "gennaio", "february": "febbraio", "march": "marzo", "april": "aprile",
    "may": "maggio", "june": "giugno", "july": "luglio", "august": "agosto",
    "september": "settembre", "october": "ottobre", "november": "novembre", "december": "dicembre",
}


# --- helper numerici / formattazione ------------------------------------

def _num(tok):
    """Token ('75K','5.7K','19.4','706','—','No data') -> numero o None."""
    if tok is None:
        return None
    t = str(tok).strip().replace("%", "").replace(",", ".")
    if t in ("—", "-", "", "No data"):
        return None
    mult = 1
    if t[-1:].upper() == "K":
        mult, t = 1000, t[:-1]
    elif t[-1:].upper() == "M":
        mult, t = 1_000_000, t[:-1]
    try:
        v = float(t) * mult
        return int(v) if v == int(v) else round(v, 2)
    except ValueError:
        return None


def _disp(tok):
    """Display all'italiana: virgola decimale, mantiene K/M ('5.7K' -> '5,7K')."""
    return (str(tok).strip().replace(".", ",")) if tok not in (None, "") else ""


def _pct(tok):
    """Variazione all'italiana ('+137.3%' -> '+137,3%'); '—'/'No data' invariati."""
    t = (str(tok).strip() if tok is not None else "")
    if t in ("—", "No data", ""):
        return t or "—"
    return t.replace(".", ",")


def _tone(delta):
    d = (delta or "").strip()
    if d.startswith("+"):
        return "green"
    if d.startswith("-"):
        return "amber"
    return "neutral"


def _pdf_text(path):
    reader = PyPDF2.PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _search(pattern, text, flags=re.DOTALL):
    m = re.search(pattern, text, flags)
    return m.groups() if m else None


# regex riutilizzabili
_VAL = r"([0-9][0-9.,KM]*|—)"
_DLT = r"([+\-][0-9.,]+%|No data|—)"


# --- parser principale ---------------------------------------------------

def parse(pdf_path):
    """Ritorna un dict DATA (parziale) + chiave 'missing_data'."""
    text = _pdf_text(pdf_path)
    missing = []
    data = {"meta": {}, "kpis": [], "split": {}, "engagement_breakdown": [],
            "rates": [], "audience_growth": [], "publishing_mix": [],
            "top_content": [], "stories": [], "hashtags": [], "geo": [],
            "timing": [], "community": [],
            "roadmap": {"continuare": [], "potenziare": [], "correggere": [], "testare": []}}

    # --- meta: brand + periodo (prime righe) ---
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    brand = lines[0] if lines else "Cliente"
    period = ""
    mp = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d+)\s*-\s*([A-Za-z]+)\s+(\d+),\s+(\d+)", text)
    if mp:
        m1, d1, y1, m2, d2, y2 = mp.groups()
        mon1 = EN_MONTHS.get(m1.lower(), m1.lower())
        mon2 = EN_MONTHS.get(m2.lower(), m2.lower())
        period = f"{d1}-{d2} {mon1} {y1}" if mon1 == mon2 and y1 == y2 else f"{d1} {mon1} - {d2} {mon2} {y2}"
    data["meta"] = {"brand": brand, "channel": "Instagram", "period": period,
                    "source": "Export Instagram / Agorapulse"}

    # --- helper per costruire una KPI card ---
    def kpi(_id, label, val, delta):
        return {"id": _id, "label": label, "value": _disp(val), "delta": _pct(delta),
                "tone": _tone(_pct(delta)), "detail": "", "action": ""}

    # Overview (followers, engagement, views, mentions)
    ov = _search(rf"Total followers\s+{_VAL}\s+{_DLT}.*?Engagement\s+{_VAL}\s+{_DLT}"
                 rf".*?Views\s+{_VAL}\s+{_DLT}.*?Mentions\s+{_VAL}\s+{_DLT}", text)
    # Views (totali/organiche/paid)
    vw = _search(rf"Views\s+{_VAL}\s+{_DLT}\s+Organic views\s+{_VAL}\s+{_DLT}"
                 rf"\s+Paid views\s+{_VAL}\s+{_DLT}", text)
    # Posts insights (nel PDF i blocchi sono attaccati: "-22.2%Posts views" -> \s*)
    pi = _search(rf"Published posts\s+{_VAL}\s+{_DLT}\s*Posts views\s+{_VAL}\s+{_DLT}"
                 rf"\s*Posts engagement\s+{_VAL}\s+{_DLT}", text)

    if ov:
        data["kpis"].append(kpi("followers", "Follower totali", ov[0], ov[1]))
        data["kpis"].append(kpi("engagement", "Engagement totale", ov[2], ov[3]))
        data["kpis"].append(kpi("views", "Views totali", ov[4], ov[5]))
    if vw:
        data["kpis"].append(kpi("organic_views", "Views organiche", vw[2], vw[3]))
        data["kpis"].append(kpi("paid_views", "Views paid", vw[4], vw[5]))
    if ov:
        data["kpis"].append(kpi("mentions", "Mention", ov[6], ov[7]))
    if pi:
        data["kpis"].append(kpi("published", "Post pubblicati", pi[0], pi[1]))
        data["kpis"].append(kpi("post_views", "Views sui post", pi[2], pi[3]))
        data["kpis"].append(kpi("post_engagement", "Engagement post", pi[4], pi[5]))

    # --- engagement breakdown (Organico Paid Totale Variazione) ---
    eb_map = [("Like", "Likes"), ("Commenti", "Comments"), ("Condivisioni", "Shares"),
              ("Salvataggi", "Saved"), ("Direct message", "Direct messages")]
    for label_it, label_en in eb_map:
        g = _search(rf"{label_en}\s+([\d—]+)\s+([\d—]+)\s+([\d—]+)\s+{_DLT}", text)
        if g:
            data["engagement_breakdown"].append({
                "label": label_it, "organic": _num(g[0]), "paid": _num(g[1]),
                "total": _num(g[2]), "variation": _pct(g[3])})
    te = _search(rf"Total engagement\s+(\d+)\s+(\d+)\s+(\d+)\s+{_DLT}", text)

    # --- split (views / engagement / reach, organico vs paid) ---
    if vw:
        data["split"]["views"] = [
            {"label": "Organiche", "value": _num(vw[2]), "display": _disp(vw[2])},
            {"label": "Paid", "value": _num(vw[4]), "display": _disp(vw[4])}]
    if te:
        dm = next((e for e in data["engagement_breakdown"] if e["label"] == "Direct message"), None)
        eng_split = [{"label": "Organico", "value": _num(te[0]), "display": te[0]},
                     {"label": "Paid", "value": _num(te[1]), "display": te[1]}]
        if dm and dm.get("total"):
            eng_split.append({"label": "DM non ripartiti", "value": dm["total"], "display": str(dm["total"])})
        data["split"]["engagement"] = eng_split
    rc = _search(rf"Average reach\s+{_VAL}\s+{_DLT}\s+Average organic reach\s+{_VAL}\s+{_DLT}"
                 rf"\s+Average paid reach\s+{_VAL}\s+{_DLT}", text)
    if rc:
        data["split"]["reach"] = [
            {"label": "Reach organica media", "value": _num(rc[2]), "display": _disp(rc[2])},
            {"label": "Reach paid media", "value": _num(rc[4]), "display": _disp(rc[4])}]

    # --- engagement rate (per view / per reach) ---
    rates = re.findall(rf"Eng\. rate[^0-9]*([\d.,]+%)\s+([\d.,]+%)\s+([\d.,]+%)\s+{_DLT}", text)
    if len(rates) >= 1:
        r = rates[0]
        data["rates"].append({"metric": "Engagement rate per view", "organic": _disp(r[0]),
                              "paid": _disp(r[1]), "total": _disp(r[2]), "variation": _pct(r[3]), "insight": ""})
    if len(rates) >= 2:
        r = rates[1]
        data["rates"].append({"metric": "Engagement rate per reach", "organic": _disp(r[0]),
                              "paid": _disp(r[1]), "total": _disp(r[2]), "variation": _pct(r[3]), "insight": ""})

    # --- audience growth (New Lost Net) ---
    ag = _search(r"Followers\s+(\d+)\s+(\d+)\s+(\d+)\s*\n[^\n]*New Lost Net growth", text)
    if ag:
        data["audience_growth"] = [
            {"label": "Nuovi follower", "value": _num(ag[0])},
            {"label": "Follower persi", "value": _num(ag[1])},
            {"label": "Crescita netta", "value": _num(ag[2])}]

    # --- publishing mix ---
    fmt_map = [("Stories", "Stories"), ("Caroselli", "Carousels"), ("Immagini", "Images"),
               ("Reel", "Reels"), ("Video", "Videos")]
    posts_counts = {}
    for label_it, label_en in fmt_map:
        g = _search(rf"{label_en}\s+(\d+)\s+{_DLT}", text)
        if g:
            posts_counts[label_it] = _num(g[0])
            data["publishing_mix"].append({"format": label_it, "posts": _num(g[0]),
                                           "variation": _pct(g[1]), "avg_engagement": 0, "share": 0.0})
    tot_posts = sum(v for v in posts_counts.values() if v) or 0
    for row in data["publishing_mix"]:
        row["share"] = round((row["posts"] / tot_posts) * 100, 1) if tot_posts and row["posts"] else 0.0

    # --- top content (3 post con statistiche complete) ---
    posts = re.findall(
        r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+Views\s+(\d+)\s+Reach\s+(\d+)\s+Engagement\s+(\d+)"
        r"\s+Likes\s+(\d+)\s+Comments\s+(\d+)\s+Saved\s+(\d+)"
        r"\s+Eng\. rate per view\s+([\d.,]+%)\s+Eng\. rate per reach\s+([\d.,]+%)", text)
    # descrizioni + tipo (in ordine): cercate SOLO nella coda dopo le statistiche
    # dei top post, cosi' ogni descrizione e' pulita e completa.
    stat_iters = list(re.finditer(
        r"\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}\s+Views\s+\d+\s+Reach\s+\d+\s+Engagement\s+\d+"
        r"\s+Likes\s+\d+\s+Comments\s+\d+\s+Saved\s+\d+"
        r"\s+Eng\. rate per view\s+[\d.,]+%\s+Eng\. rate per reach\s+[\d.,]+%", text))
    tail = text[stat_iters[-1].end():] if stat_iters else ""
    descs = re.findall(r"(.+?)\s*No label\s*(Reel|Carousel|Image|Video|Story)", tail, re.DOTALL)
    type_it = {"Reel": "Reel", "Carousel": "Carosello", "Image": "Immagine", "Video": "Video", "Story": "Story"}
    for i, p in enumerate(posts):
        desc = descs[i][0].strip() if i < len(descs) else ""
        desc = re.sub(r"\s+", " ", desc)
        ptype = type_it.get(descs[i][1], "Post") if i < len(descs) else "Post"
        topic = (desc.split(".")[0][:48]).strip() if desc else ""
        data["top_content"].append({
            "date": p[0], "time": p[1], "type": ptype, "topic": topic, "description": desc,
            "views": _num(p[2]), "reach": _num(p[3]), "engagement": _num(p[4]),
            "likes": _num(p[5]), "comments": _num(p[6]), "saved": _num(p[7]),
            "er_view": _num(p[8]), "er_reach": _num(p[9]), "insight": ""})

    # --- stories (senza Likes/Comments/Saved) ---
    stories = re.findall(
        r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+Views\s+(\d+)\s+Reach\s+(\d+)\s+Engagement\s+(\d+)"
        r"\s+Eng\. rate per view\s+[\d.,]+%\s+Eng\. rate per reach\s+[\d.,]+%", text)
    for s in stories:
        data["stories"].append({"date": s[0], "time": s[1], "views": _num(s[2]),
                                "reach": _num(s[3]), "engagement": _num(s[4])})

    # --- hashtags ---
    for tag, val in re.findall(r"#([A-Za-z0-9]+)\s*\n\s*(\d+)\s*interactions", text):
        data["hashtags"].append({"tag": "#" + tag, "value": _num(val)})

    # --- community management ---
    cm = _search(rf"Replies sent\s+{_VAL}\s+{_DLT}.*?Reviewed items\s+{_VAL}\s+{_DLT}"
                 rf".*?Deleted/Hidden items\s+{_VAL}\s+{_DLT}.*?Average response time\s+(—|[\d.,]+\s*\w*)\s+{_DLT}", text)
    if cm:
        data["community"] = [
            {"label": "Replies sent", "value": _disp(cm[0]), "variation": _pct(cm[1])},
            {"label": "Reviewed items", "value": _disp(cm[2]), "variation": _pct(cm[3])},
            {"label": "Deleted/Hidden items", "value": _disp(cm[4]), "variation": _pct(cm[5])},
            {"label": "Average response time", "value": (cm[6] or "—").strip(), "variation": _pct(cm[7])}]

    # --- cosa non e' estraibile in modo affidabile dal solo testo ---
    if not data["geo"]:
        missing.append("Distribuzione follower per citta' (nel PDF e' solo un grafico)")
    if not data["timing"]:
        missing.append("Timing/heatmap orari (solo grafico nel PDF)")
    missing.append("Demografia per eta'/genere (solo grafico nel PDF)")
    missing.append("Testi narrativi e roadmap (da generare con il motore di tono)")
    data["missing_data"] = missing
    return data
