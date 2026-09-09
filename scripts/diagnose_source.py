#!/usr/bin/env python3
"""
Where exactly does the wall stand?

`record-odds --verify` reported HTTP 503 from fixtures.csv, twice, with an
identical error page. That is one bit of information: the request failed. It
does not say whether the site is down, whether one endpoint is down, or whether
something refuses this client — and those three lead to different decisions.

So this probes several endpoints from the same runner, with the same User-Agent
and no TLS bypass, and prints what each one answers. It writes nothing, parses
nothing, and shares no code with the collector.

Two of the URLs are here for a second reason. A season file under `mmz4281`
carries PLAYED matches WITH odds, including the last few days. It cannot serve
the collector — those odds arrive after the result, so there is no instant to
record and `capture_precision` would be PREMATCH, not TIMESTAMPED. But it would
answer the retrospective question that started this, and it is worth knowing
whether it is reachable when `fixtures.csv` is not.

    python scripts/diagnose_source.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

UA = "fiorino-quant/1.0 (+research)"
TIMEOUT = 45

#: (label, url, what a 200 would tell us)
TARGETS = [
    ("ROOT", "https://www.football-data.co.uk/",
     "il sito risponde: il 503 e' dell'endpoint, non del server"),
    ("ROOT_NO_WWW", "https://football-data.co.uk/",
     "l'host senza www si comporta diversamente"),
    ("LEAGUE_PAGE", "https://www.football-data.co.uk/englandm.php",
     "le pagine HTML passano: allora il problema e' il file"),
    ("FIXTURES_CSV", "https://www.football-data.co.uk/fixtures.csv",
     "l'endpoint del collector e' tornato: si riprende da B"),
    ("SEASON_E0_2627", "https://www.football-data.co.uk/mmz4281/2627/E0.csv",
     "partite GIA' GIOCATE con quote, ultimi giorni compresi"),
    ("SEASON_D1_2627", "https://www.football-data.co.uk/mmz4281/2627/D1.csv",
     "come sopra, per confermare che non e' un caso isolato"),

    # La prima esecuzione ha risposto: il sito e' VIVO sull'host senza www e
    # 503 su tutto sull'host con www, con lo stesso User-Agent, dallo stesso
    # runner, senza TLS bypass. Non e' un rifiuto del client: e' un host rotto.
    # Questi ripetono gli stessi file sull'host che funziona.
    ("FIXTURES_CSV_NO_WWW", "https://football-data.co.uk/fixtures.csv",
     "l'endpoint del collector funziona: bastava l'host giusto"),
    ("SEASON_E0_NO_WWW", "https://football-data.co.uk/mmz4281/2627/E0.csv",
     "partite gia' giocate con quote, ultimi giorni compresi"),
    ("SEASON_D1_NO_WWW", "https://football-data.co.uk/mmz4281/2627/D1.csv",
     "come sopra, seconda conferma"),
]


def probe(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            return {"status": response.status, "bytes": len(body),
                    "head": body[:300].decode("utf-8", errors="replace"),
                    "error": None}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "bytes": 0, "head": "",
                "error": exc.read()[:300].decode(errors="replace")}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "bytes": 0, "head": "",
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    print(f"USER_AGENT={UA}")
    print("TLS_VERIFY=on  # mai disattivata")
    print("SPOOFING=none  # nessuna stringa che finge un browser\n")

    reachable = 0
    for label, url, meaning in TARGETS:
        result = probe(url)
        print(f"--- {label}")
        print(f"URL={url}")
        print(f"STATUS={result['status']}")
        print(f"BYTES={result['bytes']}")
        if result["status"] == 200:
            reachable += 1
            first = result["head"].splitlines()[0] if result["head"] else ""
            print(f"FIRST_LINE={first[:280]}")
            print(f"SIGNIFICA={meaning}")
        else:
            print(f"ERROR_HEAD={' '.join(result['error'].split())[:200]}")
        print()

    print(f"RAGGIUNGIBILI={reachable}/{len(TARGETS)}")
    if reachable == 0:
        print("LETTURA=nessun endpoint risponde. Compatibile sia con un sito "
              "giu' sia con un rifiuto di questo client: questo test da solo "
              "non li distingue, e non va usato per concludere il secondo.")
    elif reachable < len(TARGETS):
        print("LETTURA=il server risponde ad alcuni endpoint e non ad altri, "
              "quindi non e' giu'. Il problema e' l'endpoint che fallisce.")
    else:
        print("LETTURA=tutto raggiungibile: il 503 precedente era transitorio.")
    # Always 0: this is a measurement, and a measurement that reports a wall
    # has succeeded at its job.
    return 0


if __name__ == "__main__":
    sys.exit(main())
