"""
Le due statistiche di clv_lab che decidono cosa e' un risultato.

Nessuna delle due era verificabile prima: gli errori standard trattavano 27
righe della stessa partita come 27 osservazioni indipendenti, e le celle
misuravano il livello assoluto del CLV, che sotto de-vig moltiplicativo e'
il margine del book per identita' aritmetica e non per misura.

I dati veri stanno su football-data.co.uk, irraggiungibile da questo ambiente.
Questi test non ne hanno bisogno: costruiscono righe di cui si conosce la
risposta, che e' una verifica piu' forte, non piu' debole.
"""

import statistics as st

from scripts.clv_lab import cell, contrasto_dentro_il_book


def riga(match, book, clv, is_best=False):
    return {"season": "2526", "div": "E0", "book": book, "sel": "HOME",
            "price": 2.0, "clv": clv, "won": False, "band": "1.6-2.2",
            "tier": "TOP", "match": match, "is_best": is_best}


class TestGliErroriStandardSonoRaggruppatiPerPartita:
    def test_righe_identiche_nella_stessa_partita_non_aggiungono_informazione(self):
        """Il caso limite: 27 copie della stessa osservazione sono UNA
        osservazione. L'errore standard ingenuo le conta tutte e si restringe
        di sqrt(27); quello raggruppato no. Il design effect deve valere ~27."""
        import random
        rng = random.Random(4)
        rows = []
        for m in range(300):
            valore = rng.gauss(-0.05, 0.30)
            for k in range(27):
                rows.append(riga(f"M{m}", f"BOOK{k}", valore))
        misura = cell(rows, "prova")
        assert 20 < misura["deff"] < 34, misura["deff"]

    def test_una_riga_per_partita_lascia_il_design_effect_a_uno(self):
        """Senza raggruppamento non c'e' niente da correggere: se la
        correzione gonfiasse anche qui, sarebbe una penalita' arbitraria."""
        import random
        rng = random.Random(5)
        rows = [riga(f"M{m}", "BET365", rng.gauss(-0.05, 0.30))
                for m in range(3000)]
        misura = cell(rows, "prova")
        assert 0.85 < misura["deff"] < 1.15, misura["deff"]


class TestIlContrastoDentroIlBookCancellaIlMargine:
    @staticmethod
    def costruisci(rng, margini, effetto, partite=2000, rumore=0.08):
        """Ogni book ha il SUO margine, che e' il livello del suo CLV, e la
        stessa regola aggiunge `effetto` ovunque. Un metodo che misura livelli
        assoluti vede i margini; uno che misura la regola vede `effetto`."""
        rows = []
        for m in range(partite):
            for book, margine in margini.items():
                for k in range(3):
                    is_best = k == 0
                    clv = -margine + (effetto if is_best else 0.0)
                    rows.append(riga(f"M{m}", book,
                                     clv + rng.gauss(0, rumore), is_best))
        return rows

    def test_recupera_un_effetto_noto_identico_sotto_margini_diversi(self):
        import random
        rng = random.Random(7)
        margini = {"MARKET_MAX": 0.018, "BET365": 0.067, "SKYBET": 0.107}
        rows = self.costruisci(rng, margini, effetto=0.02)

        # I livelli assoluti sono i margini: e' cio' che la vecchia tabella
        # per book stava misurando.
        for book, margine in margini.items():
            livello = st.mean(r["clv"] for r in rows if r["book"] == book)
            assert abs(livello - (-margine + 0.02 / 3)) < 0.01, (book, livello)

        # Il contrasto invece e' lo stesso per tutti e tre, entro l'errore.
        # L'effetto atteso vale circa nove errori standard con questo n:
        # la soglia non e' tarata sul risultato, e' scelta perche' il disegno
        # abbia potenza abbondante contro il vero effetto iniettato.
        for d in contrasto_dentro_il_book(rows, replicas=80):
            assert abs(d["diff"] - 0.02) < 0.006, d
            assert d["t"] > 4, d
            # L'errore del bootstrap sulle partite deve coincidere con quello
            # analitico: se divergesse, il t sarebbe inventato.
            atteso = 0.08 * (1 / 2000 + 1 / 4000) ** 0.5
            assert 0.6 * atteso < d["se"] < 1.6 * atteso, (d, atteso)

    def test_senza_effetto_il_contrasto_non_ne_inventa(self):
        import random
        rng = random.Random(8)
        rows = self.costruisci(rng, {"BET365": 0.067, "SKYBET": 0.107},
                               effetto=0.0)
        for d in contrasto_dentro_il_book(rows, replicas=80):
            assert abs(d["t"]) < 3, d
