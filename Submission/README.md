<p align="center">
  <img src="06_Logo/png/serce-okolicy-poziome.png" alt="Serce Okolicy" width="420">
</p>

# Serce Okolicy — materiały zgłoszeniowe

**„Masz AED? Pokaż, gdzie!”**
Ogólnopolski, otwarty rejestr defibrylatorów AED na dane.gov.pl i kampania, która zachęca właścicieli urządzeń do ich zgłaszania i aktualizowania.

Wyzwanie **Misja AED — Dane na ratunek** · HackNation 2026 · Ministerstwo Cyfryzacji

---

## Struktura folderu

Foldery odpowiadają wymaganiom formalnym z treści zadania (§ 4) w tej samej kolejności. Kod źródłowy (wymaganie 5) znajduje się w tym repozytorium.

```
Submission/
├── 01_Opis_projektu/            Tytuł i szczegółowy opis projektu
├── 02_Prezentacja/              Prezentacja (PDF, PPTX)
├── 03_Prototyp/                 Uruchomienie prototypu i przykładowy eksport danych
│   └── eksport_dane_gov_pl/     CSV, GeoJSON i metadane gotowe do publikacji
├── 04_Wzorcowy_zakres_danych/   Wzorcowy zakres danych o AED (XLSX)
├── 06_Logo/                     Logotyp: svg/ · pdf/ · png/ · jpg/
├── 07_Ksiega_znaku/             Księga znaku (PDF)
├── 08_Wykorzystanie_AI/         Zakres wykorzystania sztucznej inteligencji
└── 09_Materialy_dodatkowe/      Film kampanii, okładka, linki
```

## Zawartość

| Folder | Pliki | Wymaganie |
|---|---|---|
| [`01_Opis_projektu`](01_Opis_projektu/) | `Serce-Okolicy-opis-projektu.pdf` (+ `.md`) | Szczegółowy opis i tytuł projektu |
| [`02_Prezentacja`](02_Prezentacja/) | `Serce Okolicy — prezentacja.pdf`, `.pptx` — 10 slajdów: problem, rozwiązanie, zrzuty ekranu i kroki użytkownika, kampania, finanse, ograniczenia | Prezentacja |
| [`03_Prototyp`](03_Prototyp/) | `URUCHOMIENIE.txt`; `eksport_dane_gov_pl/`: `aed.csv`, `aed.geojson`, `portal-metadata.json` (15 299 punktów, stan 22.11.2026) | Prototyp rozwiązania; format odczytywalny maszynowo |
| [`04_Wzorcowy_zakres_danych`](04_Wzorcowy_zakres_danych/) | `wzorcowy-zakres-danych-AED.xlsx` — instrukcja, szablon, opis 31 pól, słowniki, przykłady, metadane zbioru | Wzorcowy zakres danych (XLSX) |
| [`06_Logo`](06_Logo/) | 10 wariantów × 4 formaty (SVG, PDF, PNG z przezroczystym tłem, JPG) | Logotyp w .jpg, .png, .pdf i formacie otwartym |
| [`07_Ksiega_znaku`](07_Ksiega_znaku/) | `Serce-Okolicy-ksiega-znaku.pdf` — 8 stron: logo, kolorystyka, typografia, ikony, komponenty, kampania | Księga znaku w PDF |
| [`08_Wykorzystanie_AI`](08_Wykorzystanie_AI/) | `Wykorzystanie-AI.txt` | Regulamin § 2 ust. 8 |
| [`09_Materialy_dodatkowe`](09_Materialy_dodatkowe/) | `Serce-Okolicy-v4.mp4` (film 90 s), `Serce-Okolicy-cover.jpg`, `LINKI.md` | — |

### Warianty logo (`06_Logo/`)

| Plik | Zastosowanie |
|---|---|
| `serce-okolicy-poziome` | Logo podstawowe na jasnym tle |
| `serce-okolicy-poziome-negatyw` | Logo podstawowe na ciemnym tle |
| `serce-okolicy-pionowe` / `-pionowe-negatyw` | Naklejki, plakaty, formaty kwadratowe |
| `serce-okolicy-sygnet` | Sam znak: ikona aplikacji, awatar |
| `serce-okolicy-sygnet-maly` | 32 px i mniej, favicon |
| `serce-w-okolicy-poziome` | Wariant dla edycji lokalnych |
| `serce-okolicy-mono-kremowe` / `-zielone` / `-czarne` | Wersje jednobarwne: zdjęcia, druk jednokolorowy, pieczątka |

## Uruchomienie prototypu

Wymagany Python 3.10+ (z SQLite R\*Tree).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python prepare_data.py --refresh   # pobiera i scala źródła
.venv/bin/python server.py --host 127.0.0.1 --port 8000
```

Następnie: mapa `http://127.0.0.1:8000/app` · zgłoszenia `/zglos` · panel redaktora `/panel` (token w `data/admin-token`). Szczegóły w README repozytorium.

## Linki

- Strona kampanii: https://rodrigogaluppo.github.io/HACK_NATION_Serce_Okolicy/
- Film: https://www.youtube.com/watch?v=yONkNapDy-4

## Wykorzystanie AI

Pomysł, koncepcja rozwiązania i kampanii „Masz AED? Pokaż, gdzie!” są nasze. Sztuczną inteligencję wykorzystaliśmy jako narzędzie pomocnicze do:

- wyszukiwania informacji i agregacji danych o defibrylatorach AED z wielu źródeł,
- pisania kodu oraz testowania tras (endpointów) aplikacji pod kątem bezpieczeństwa,
- przygotowania filmu i ikon,
- wygenerowania logo — w toku rozmowy z AI, na podstawie naszych założeń i naszej identyfikacji wizualnej.

Wszystkie wyniki pracy AI przejrzeliśmy, poprawiliśmy i zatwierdziliśmy. Pełne oświadczenie: [`08_Wykorzystanie_AI/Wykorzystanie-AI.txt`](08_Wykorzystanie_AI/Wykorzystanie-AI.txt).

## Licencje danych i zasobów

- Dane OpenStreetMap / OpenAEDMap: © współtwórcy OpenStreetMap, ODbL 1.0.
- Zbiory miast z dane.gov.pl: Krosno, Przemyśl i Legionowo — CC0 1.0; Marki — CC BY 4.0.
- Lista AED InPost: publiczny wykaz operatora; warunki ponownego wykorzystania do potwierdzenia.
- Kroje Bebas Neue i DM Sans: SIL Open Font License.
