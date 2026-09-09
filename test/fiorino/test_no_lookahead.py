"""
La classe di errore in cui questo progetto e' caduto due volte.

M6: il braccio MARKET mostrava +0.0234 di CLV, e si e' rivelato definitorio —
era costruito in modo da essere corretto al momento della scommessa.

movement_lab, prima versione: selezionava le righe in cui il mercato si era
mosso verso un esito, e poi segnava quelle righe contro la chiusura. La stessa
chiusura da entrambe le parti. Il risultato era spettacolare — +0.0440 con
t=+45.8, dose-risposta monotona, controllo negativo che si comportava
correttamente, replica su due stagioni — e completamente vuoto: la stessa
selezione su un mercato simulato con ZERO segnale produce +0.0702, cioe' un
artefatto piu' grande dell'effetto.

Quel test e' qui perche' la prossima volta non serva accorgersene di nuovo: un
criterio di selezione che tocca il futuro produce un edge anche quando il
futuro e' rumore puro.
"""

import random
import statistics as st


def simulate(select_on_closing: bool, trials: int = 60_000, seed: int = 20260909):
    """Un mercato senza alcun segnale. Ogni book stima la stessa probabilita'
    vera con rumore indipendente; la chiusura e' la verita' piu' rumore.
    Nessuno e' lento, nessuno sa niente, non c'e' niente da trovare."""
    rng = random.Random(seed)
    picked = []
    for _ in range(trials):
        true_p = rng.uniform(0.15, 0.60)
        books = [true_p + rng.gauss(0, 0.020) for _ in range(6)]
        close = true_p + rng.gauss(0, 0.020)
        i = rng.randrange(6)
        mine, others = books[i], books[:i] + books[i + 1:]
        price = 1.0 / (mine * 1.06)
        clv = close * price - 1.0
        deviation = mine - st.median(others)
        if deviation >= -0.005:
            continue
        if select_on_closing and close - st.median(books) <= 0.010:
            continue
        picked.append(clv)
    return st.mean(picked), len(picked)


def test_selecting_on_the_closing_price_manufactures_an_edge_from_nothing():
    """Il punto: la selezione circolare produce un CLV POSITIVO su un mercato
    dove per costruzione non c'e' vantaggio."""
    mean, n = simulate(select_on_closing=True)
    assert n > 1_000
    assert mean > 0.02, (
        "l'artefatto e sparito: se questa asserzione fallisce, la simulazione "
        "non riproduce piu' l'errore che il test esiste per ricordare"
    )


def test_selecting_only_on_what_is_known_at_bet_time_does_not():
    """Lo stesso mercato, la stessa soglia sullo scostamento, ma senza toccare
    la chiusura nella selezione: il CLV torna negativo, cioe' il margine."""
    mean, n = simulate(select_on_closing=False)
    assert n > 1_000
    assert mean < 0, (
        "una selezione che usa solo informazione nota all'apertura non puo "
        "produrre un edge su un mercato senza segnale"
    )


def test_the_gap_between_the_two_is_the_whole_lesson():
    circular, _ = simulate(select_on_closing=True)
    honest, _ = simulate(select_on_closing=False)
    assert circular - honest > 0.05, (
        "il divario fra selezione circolare e selezione onesta e la misura "
        "dell'illusione, e sui dati veri valeva piu di dieci punti di CLV"
    )
