# Serce Okolicy — ogólnopolski, otwarty rejestr defibrylatorów AED na dane.gov.pl

**Hasło kampanii:** „Masz AED? Pokaż, gdzie!”  
**Wyzwanie:** Misja AED — Dane na ratunek · HackNation 2026 · Ministerstwo Cyfryzacji  
**Zespół:** [Imię i nazwisko] · [Imię i nazwisko] · [Imię i nazwisko]  
**Stan na:** 22.11.2026

---

## 1. W skrócie

Serce Okolicy łączy rozproszone dane o defibrylatorach AED w jeden otwarty, ogólnopolski zbiór gotowy do publikacji na dane.gov.pl. Daje wszystkim dysponentom wspólny, wzorcowy zakres danych (XLSX), a właścicielom urządzeń powód, żeby je zgłaszali i aktualizowali. Za zweryfikowane zgłoszenie dziękujemy, pilnujemy terminów baterii i elektrod, a tam, gdzie AED ratuje najczęściej, pomagamy sfinansować ich wymianę.

## 2. Problem

Podczas nagłego zatrzymania krążenia nawet poprawny adres AED może doprowadzić świadka do zamkniętych drzwi. W polskim badaniu (Żuratyński i in., *Medicina* 2021, 57(3):298) tylko 54% placówek, które odpowiedziały na ankietę, zapewniało całodobowy dostęp do urządzenia.

Informacje o AED są rozproszone między rejestrami, mapami i arkuszami. To samo urządzenie bywa w nich opisane inaczej, z różnymi współrzędnymi. W zebranym przez nas zestawieniu 58,5% wpisów nie podaje godzin dostępu, a żaden ze 15 299 punktów nie mówi, czy urządzenie działa. Dysponenci nie mają prostego sposobu, by przekazać dane i zgłaszać zmiany, więc mieszkańcom i ratownikom trudno ustalić, któremu wpisowi zaufać.

## 3. Rozwiązanie

### 3.1. Jeden zbiór z wielu źródeł (prototyp — działa)
- **Import z 6 źródeł:** OpenAEDMap/OpenStreetMap, zbiory miast Krosno, Przemyśl, Marki i Legionowo z dane.gov.pl oraz lista AED InPost. Adapter dla Warszawy jest gotowy i włącza się po podaniu tokenu API; 8 rejestrów regionalnych i sektorowych czeka na adaptery.
- **Ujednolicenie i scalanie:** normalizacja adresów i współrzędnych, wyszukiwanie duplikatów w promieniu do 30 m (adres, nazwa, odległość), automatyczna naprawa zamienionych osi współrzędnych.
- **Kontrola jakości:** rekordy sprzeczne lub podejrzane (np. współrzędne poza gminą, wspólne współrzędne różnych adresów) trafiają do kolejki weryfikacji zamiast na mapę — w bieżącej migawce 23 rekordy.
- **Pochodzenie każdego pola:** zbiór zapisuje, które źródło dostarczyło każdą informację, oraz ocenę kompletności dokumentacji (0–100). Ocena nigdy nie udaje sprawności urządzenia: bez kontroli status gotowości to `unknown`.
- **Ochrona prywatności:** automatyczne usuwanie e-maili, prywatnych telefonów i kodów PIN z opisów.
- **Wynik:** 15 299 punktów AED, odświeżanych automatycznie co 24 godziny.

### 3.2. Wzorcowy zakres danych (XLSX)
Plik `wzorcowy-zakres-danych-AED.xlsx` opisuje 31 pól: 30 pól zbioru publikowanego i identyfikator urządzenia u dysponenta. Zawiera szablon do wypełnienia z listami wyboru i walidacją współrzędnych, słowniki wartości, prawdziwe przykłady oraz zalecane metadane zbioru dla dane.gov.pl. Pierwsze 16 kolumn szablonu to format formularza zgłoszeń prototypu — wypełniony plik można wgrać bez zmian.

### 3.3. Publikacja na dane.gov.pl
- Formaty odczytywalne maszynowo: **CSV** (UTF-8, RFC 4180, ochrona przed formułami), **GeoJSON** (RFC 7946, WGS84), **JSON**.
- Plik metadanych z tytułem, opisem, kategorią „Zdrowie”, słowami kluczowymi, częstotliwością aktualizacji, sumami kontrolnymi SHA-256 i licencją każdego źródła.
- Panel redaktora eksportuje komplet (CSV, GeoJSON, JSON, metadane, XLSX) jako jedną paczkę ZIP.
- Przykładowy eksport z 22.11.2026 jest w folderze `03_Prototyp/eksport_dane_gov_pl/`.

### 3.4. Mapa dla mieszkańców i ratowników
Mobilna, dwujęzyczna (PL/EN) aplikacja webowa: wyszukiwanie po mieście lub adresie, filtry dostępności i jakości danych, a przy każdym punkcie wejście, kondygnacja, godziny dostępu, data ostatniego sprawdzenia i źródło. Wybrany obszar można zapisać w przeglądarce — punkty AED i uproszczona mapa ulic działają bez internetu.

### 3.5. Zgłoszenia i weryfikacja
- **Formularz „Dodaj AED”:** jedno urządzenie przez formularz albo wiele przez plik XLSX, CSV lub GeoJSON (do 500 w pliku). Najpierw podgląd błędów, potem wysłanie.
- **Panel redaktora:** kolejka zgłoszeń do zatwierdzenia lub odrzucenia, stan źródeł, ręczna synchronizacja, dodawanie nowych publicznych źródeł GeoJSON. Zatwierdzony rekord od razu trafia do zbioru.

## 4. Kampania „Masz AED? Pokaż, gdzie!”

**Nazwa akcji:** Serce Okolicy. Każdy AED to serce swojej okolicy. Logo rysuje to serce jako plan ulic z jednym punktem — urządzeniem na Twoim rogu.

**Obietnica:** „Pokaż nam swój AED. My przypilnujemy, żeby był dostępny.”

**Mechanizm:** zgłoszenie → weryfikacja → podziękowanie. Nagroda trafia do zgłoszenia dopiero po weryfikacji, więc fikcyjne wpisy nic nie dają.

| Poziom | Kto | Co dostaje |
|---|---|---|
| Powitanie | Każdy zweryfikowany opiekun | Osobisty list, zestaw opiekuna (przypinka, zielona naklejka z kodem QR, karta RKO), bezpłatne przypomnienia o terminach baterii i elektrod, rabat 10–15% od dostawcy |
| Opieka na stałe | Wszyscy opiekunowie | Przypomnienia przy każdym terminie i prośba o potwierdzenie stanu — dane odświeżają się same |
| Dofinansowanie | Miejsca spełniające 4 warunki: duża liczba zdarzeń, kończący się termin, brak środków, publiczny dostęp | Do ~50% lub całość wymiany baterii i elektrod; opcjonalnie czujnik LoRa zgłaszający stan |

**Dlaczego to działa — porównanie (szacunki zespołu):**

| | A · Sam apel „wypełnij formularz” | B · Darmowe baterie dla wszystkich | C · Serce Okolicy |
|---|---|---|---|
| Koszt roku 1 | ~50–150 tys. zł | ~14 mln zł (~20 000 AED × ~700 zł) | ~0,6–1,1 mln zł |
| Co dostaje opiekun | Nic | Baterię, także gdy niepotrzebna | Podziękowanie, przypomnienia, rabat |
| Dane po roku | Jednorazowy wpis, który się starzeje | Jednorazowy wpis | Każdy termin baterii = nowe potwierdzenie |
| Ryzyko fikcyjnych zgłoszeń | Niskie, ale mało zgłoszeń | Wysokie | Niskie — nagroda po weryfikacji |

**Finanse roku 1 (szacunki):** zestawy powitalne 120–200 tys. zł (~8 000 × 15–25 zł) · przypomnienia e-mail ≈ 0 zł · rabat bazowy 0 zł (finansuje dostawca) · komunikacja przez partnerów 50–150 tys. zł · dofinansowanie 400–800 tys. zł (1 000–2 000 AED × ~400 zł). **Razem ~0,6–1,1 mln zł**, ok. 50–70 zł za każdy nowy AED w zbiorze; cel: 3–5 tys. nowych AED w roku 1.

**Identyfikacja wizualna:** paleta oparta na zielono-białym znaku AED (ISO 7010), krój Bebas Neue (hasła, logotyp) i DM Sans (tekst), oba na licencji OFL. Księga znaku opisuje kolorystykę z obliczonymi kontrastami WCAG, pole ochronne, minimalne wielkości, warianty i niedozwolone użycie.

## 5. Kroki użytkownika

**Mieszkaniec lub ratownik**

1. Otwiera mapę, wpisuje miasto lub adres albo używa swojej lokalizacji.
2. Wybiera najbliższy punkt i sprawdza wejście, godziny dostępu i datę ostatniego sprawdzenia.
3. Opcjonalnie zapisuje swoją okolicę, żeby mapa działała bez internetu.

**Właściciel lub opiekun AED**

1. Wchodzi na „Dodaj AED” i wypełnia formularz albo pobiera wzorcowy arkusz dla wielu urządzeń.
2. Klika „Sprawdź dane” — widzi błędy przed wysłaniem.
3. Wysyła zgłoszenie do zatwierdzenia; po weryfikacji dostaje podziękowanie i przypomnienia.

**Redaktor danych**

1. Loguje się do panelu tokenem administratora.
2. Zatwierdza lub odrzuca zgłoszenia i przegląda rekordy z kolejki weryfikacji.
3. Synchronizuje źródła i eksportuje paczkę do publikacji na dane.gov.pl.

## 6. Dostępność i responsywność
- Interfejs po polsku i angielsku, `lang="pl"`, link „Przejdź do treści”, etykiety pól i przyciski z opisem.
- Test automatyczny w przeglądarce sprawdza widok na telefonie (390 px, bez przewijania w poziomie) i pracę offline.
- Kolory marki mają obliczone kontrasty WCAG 2.x; status nigdy nie jest przekazywany samym kolorem.
- Pełny audyt WCAG 2.1 AA jest w planie — patrz ograniczenia.

## 7. Ograniczenia
- Rabaty i dofinansowanie wymagają umów z dostawcami i źródła finansowania; koszty to szacunki zespołu do sprawdzenia w pilotażu.
- Żadne źródło nie podaje sprawności AED — potwierdzą ją dopiero opiekunowie. Pola terminów baterii i elektrod oraz niepublikowany kontakt do opiekuna to kolejny krok.
- Warszawa wymaga tokenu API; 8 rejestrów regionalnych i sektorowych czeka na adaptery.
- Dane OpenStreetMap są na licencji ODbL 1.0 (zbiór pochodny musi zachować tę licencję); warunki ponownego wykorzystania listy InPost wymagają potwierdzenia.
- Prototyp działa lokalnie (Python + SQLite); strona kampanii jest publiczna na GitHub Pages.
- Nie wykonano jeszcze pełnego audytu WCAG 2.1 AA.

## 8. Zawartość zgłoszenia i linki
| Element | Gdzie |
|---|---|
| Opis i tytuł | `01_Opis_projektu/` |
| Prezentacja | `02_Prezentacja/` · https://claude.ai/artifact/K9eqo627hqTaMjdaLkxoDk |
| Prototyp | `03_Prototyp/` — instrukcja uruchomienia i przykładowy eksport |
| Wzorcowy zakres danych (XLSX) | `04_Wzorcowy_zakres_danych/` |
| Kod źródłowy | https://github.com/rodrigogaluppo/HACK_NATION_Serce_Okolicy |
| Logotyp (SVG, PDF, PNG, JPG) | `06_Logo/` |
| Księga znaku (PDF) | `07_Ksiega_znaku/` |
| Wykorzystanie AI | `08_Wykorzystanie_AI/` |
| Strona kampanii | https://rodrigogaluppo.github.io/HACK_NATION_Serce_Okolicy/ |
| Film | https://www.youtube.com/watch?v=yONkNapDy-4 |
