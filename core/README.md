# core/ — Logica e agenti AI

Qui vive il "motore": la connessione all'AI (OpenRouter), la memoria
clienti (Qdrant), la generazione dei Piani Editoriali, l'analisi dei
report e la ricerca competitor.

È tenuto separato dall'interfaccia (`app/`) di proposito: così il
motore si può riusare anche se un domani cambiamo il tipo di interfaccia.
