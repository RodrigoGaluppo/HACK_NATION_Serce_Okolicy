"use strict";
(() => {
  const words = {
    "Przejdź do wyników":"Skip to results", "O projekcie":"About", "Mapa AED":"AED map", "Zgłoś AED":"Submit an AED", "Panel danych":"Data panel",
    "Zainstaluj aplikację":"Install app", "Pomoc jest bliżej.":"Help is closer.", "SERCE OKOLICY / MAPA AED":"SERCE OKOLICY / AED MAP",
    "Znajdź defibrylator. Sprawdź dostęp. Zapisz mapę na później.":"Find a defibrillator. Check access. Save your map for later.",
    "Zapisana mapa ulic · poza obszarem mapa uproszczona":"Saved streets · simplified map outside saved area",
    "Ulice i budynki offline":"Offline streets and buildings", "Pobierz małą mapę wokół środka widoku. Ulice, budynki i woda działają lokalnie w zapisanym obszarze. Bez wyznaczania trasy.":"Download a small map around the view centre. Streets, buildings and water render locally in the saved area. Routing is unavailable.", "Promień mapy":"Map radius", "Pobierz mapę ulic":"Download street map", "Eksportuj mapę":"Export map", "Import mapy (.map.geojson)":"Import map (.map.geojson)", "Brak pobranej mapy ulic. Uproszczona mapa Polski jest już dostępna offline.":"No street map saved. The simplified Poland map is already available offline.", "Pobieranie mapy ulic i budynków…":"Downloading streets and buildings…", "Mapa zapisana na tym urządzeniu. W trybie offline pojawią się pobrane ulice i budynki.":"Map saved on this device. Downloaded streets and buildings will appear offline.", "Mapa zaimportowana lokalnie. Połączenie z serwerem nie było potrzebne.":"Map imported locally without a server connection.", "Najpierw pobierz lub zaimportuj mapę.":"Download or import a map first.", "Pobranie nowego obszaru wymaga internetu. Możesz zaimportować zapisany plik mapy.":"Downloading a new area requires internet. You can import a saved map file.",
    "Źródła danych":"Data sources", "Pobierz obszar offline":"Save area offline", "+ Oznacz AED":"+ Mark an AED", "Gdzie szukasz AED?":"Where do you need an AED?",
    "Miejscowość, adres lub nazwa miejsca":"Town, address or place name", "Szukaj":"Search", "Moja lokalizacja":"My location", "Filtry mapy":"Map filters", "Źródło danych":"Data source",
    "Wszystkie źródła":"All sources", "Moje lokalne punkty":"My local points", "Jakość dowodów":"Evidence quality", "Wszystkie poziomy":"All levels", "Średnia i wysoka (≥45)":"Medium and high (≥45)", "Wysoka (≥70)":"High (≥70)",
    "Tylko dostęp publiczny":"Reported public access only", "Ocena dotyczy jakości danych. Sprawność urządzenia wymaga osobnego potwierdzenia.":"Scores describe data quality. Device readiness needs a separate check.",
    "punktów w rejestrze":"registry points", "lokalnych":"local", "W pobliżu":"Nearby", "Promień":"Radius", "Cała Polska":"All Poland", "Twoja okolica":"Your area",
    "Szukaj przy przesuwaniu":"Search as I move", "+ Punkt na mapie":"+ Map point", "Mapa offline":"Offline map", "Odśwież widok":"Search this area", "Pełny ekran":"Full screen", "Mapa i lista":"Map and list",
    "Wysoka pewność (70–100)":"High evidence (70–100)", "Średnia pewność (45–69)":"Medium evidence (45–69)", "Niska / wymaga weryfikacji (<45)":"Low / needs review (<45)", "Otagowane lokalnie / PWA":"Local points",
    "Pracujesz offline":"You are offline", "Przeglądasz zapisane punkty. Mapa uproszczona i własne oznaczenia działają bez internetu.":"Browsing saved points. The simplified map and local notes work without internet.", "+ Taguj lokalizację":"+ Mark a location", "Eksport / Import JSON":"Export / import JSON", "Zapisane na urządzeniu":"Saved on device",
    "Dodaj punkt:":"Add a point:", "Kliknij miejsce na mapie. Oznaczenie pozostanie na tym urządzeniu, dopóki nie prześlesz go do weryfikacji.":"Click a place on the map. Your point stays on this device until you submit it for review.",
    "Oznacz miejsce AED":"Mark an AED location", "WERYFIKACJA TERENOWA & OFFLINE PWA":"FIELD NOTES / OFFLINE", "Zamknij":"Close",
    "Punkt zapiszesz na tym urządzeniu, także offline. Przesłane zgłoszenia trafią do weryfikacji przed publikacją.":"Save this point on your device, including offline. Submitted reports are reviewed before publication.",
    "Twoja ocena lokalizacji — deklaracja":"Your location assessment — self reported", "95% · Wysoka":"95 · Observed", "75% · Potwierdzona":"75 · Reported", "50% · Orientacyjna":"50 · Approximate",
    "Naoczna weryfikacja szafki i urządzenia na miejscu":"Cabinet and device seen in person", "Potwierdzone w budynku / u zarządcy obiektu":"Reported by the site or its operator", "Zgłoszenie wstępne – wymaga weryfikacji":"Initial report — needs review",
    "Nazwa miejsca / obiektu *":"Place / facility name *", "Miejscowość *":"Town *", "Szerokość geogr. (latitude) *":"Latitude *", "Długość geogr. (longitude) *":"Longitude *", "Ulica":"Street", "Numer budynku / kod pocztowy":"Building number / postcode", "Gdzie dokładnie jest szafka AED? *":"Where exactly is the AED cabinet? *", "Piętro / kondygnacja":"Floor / level", "Stan zamka szafki":"Cabinet lock", "Rodzaj dostępu":"Access type", "Godziny dostępności":"Opening hours", "Wskazówki dotarcia (bez kodów PIN i danych osobowych)":"Directions (no PIN codes or personal details)", "Zapisz punkt lokalnie":"Save point locally", "Użyj środka mapy":"Use map centre", "Nieznany":"Unknown", "Nieznany (unknown)":"Unknown", "Publiczny (public)":"Public", "Ograniczony (restricted)":"Restricted", "Otwarta / bez zamka (unlocked)":"Unlocked", "Zamknięta / alarm lub recepcja (locked)":"Locked", "Nie dotyczy (not_applicable)":"Not applicable",
    "Twoja mapa offline":"Your offline map", "ZAPISZ / PRZENIEŚ / KORZYSTAJ":"SAVE / TRANSFER / EXPLORE", "Zapisz okolicę":"Save an area", "Pobiera lokalizacje AED wokół środka mapy oraz podkład wektorowy JS do pamięci podręcznej przeglądarki (CacheStorage + LocalStorage).":"Saves points around the map centre on this device.",
    "Zapisz punkty wokół środka mapy. Aplikacja i uproszczona mapa Polski działają lokalnie; szczegółowe ulice wymagają internetu.":"Save points around the map centre. The app and simplified Poland map work locally; detailed streets require internet.", "Promień (km):":"Radius (km):", "Zapisz bazę w przeglądarce":"Save on this device", "Przenieś swoje dane":"Transfer your data",
    "Pobierz zapisane punkty i oznaczenia jako JSON, GeoJSON lub CSV ze wspólnym zakresem pól. Pliki lokalne mogą zawierać niezatwierdzone zgłoszenia.":"Download saved points and notes as JSON, GeoJSON or CSV with shared fields. Local files may include unreviewed reports.", "Eksportuj GeoJSON (.geojson)":"Export GeoJSON", "Eksportuj JSON":"Export JSON", "Eksportuj CSV":"Export CSV", "Eksportuj tylko moje tagi (.geojson)":"Export my points only", "Dodaj plik do swojej mapy":"Add a file to your map",
    "Wybierz JSON, GeoJSON lub CSV. Poprawne punkty zapiszesz na urządzeniu bez połączenia z serwerem. Publikacja wymaga osobnego zatwierdzenia.":"Choose JSON, GeoJSON or CSV. Valid points are saved locally without a server connection. Publication requires a separate approval.", "Importuj do mapy PWA":"Import to local map", "Synchronizuj tagi z serwerem":"Submit points for review", "Wyczyść lokalne tagi":"Clear local points",
    "Źródła mapy":"Map sources", "POCHODZENIE / AKTUALNOŚĆ / POBIERANIE":"ORIGIN / FRESHNESS / DOWNLOADS", "Otwarte dane, sprawdzalne pochodzenie.":"Open data with traceable origins.",
    "Każdy punkt zachowuje źródła i daty dostępnych obserwacji. Brak informacji o dostępie lub sprawności oznacza „nieznane”. Pobierz rejestr w spójnym formacie JSON, GeoJSON lub CSV.":"Each point retains its sources and available observation dates. Missing access or readiness evidence stays unknown. Download the registry as JSON, GeoJSON or CSV.",
    "Pobierz pełny aed.geojson":"Download aed.geojson", "Pobierz aed_registry.json":"Download aed_registry.json", "Pobierz aed.csv":"Download aed.csv", "Wzorcowy zakres XLSX":"XLSX template",
    "Oznacz / popraw dane":"Mark / correct details", "GeoJSON punktu":"Point GeoJSON", "Usuń lokalny tag":"Remove local point", "Proweniencja pól (dane.gov.pl)":"Field provenance", "Współrzędne WGS84":"WGS84 coordinates", "Wysoka pewność":"High evidence", "Średnia pewność":"Medium evidence", "Niska pewność":"Low evidence", "Szafka otwarta":"Cabinet unlocked", "Szafka zamknięta":"Cabinet locked", "Bez szafki":"No cabinet", "Zamek nieznany":"Lock unknown",
    "Wczytywanie punktów AED…":"Loading AED points…", "Ładowanie punktów AED…":"Loading AED points…", "Brak punktów spełniających kryteria. Zmień promień, filtr lub oznacz nowy punkt AED.":"No matching points. Adjust the radius or filters, or mark a new AED.", "OpenStreetMap · przesuwaj, aby szukać":"OpenStreetMap · move to search", "Mapa uproszczona · zapisane punkty":"Simplified map · saved points", "Mapa uproszczona · dostępna offline":"Simplified map · available offline", "Włącz kafelki OSM":"Show OSM streets", "Podkład JS Offline":"Offline map",
  };
  const patterns = [
    [/^(\d[\d\s\u00a0]*) punktów w wynikach$/, "$1 points in results"],
    [/^Offline · (\d+) punktów/, "Offline · $1 points"],
    [/^W pamięci przeglądarki: (.+) pkt z bazy \+ (.+) otagowanych lokalnie\.$/, "$1 saved registry points + $2 local points."],
    [/^W pamięci lokalnej: (.+) bieżących punktów \+ (.+) otagowanych lokalnie\.$/, "$1 recent points + $2 local points."],
    [/^Zapisano lokalnie: (.+)\. Publikacja wymaga zatwierdzenia\.$/, "Saved locally: $1. Publication requires approval."],
    [/pamięć Cache z /g,"saved at "], [/^Dostęp: /, "Access: "], [/^Publiczny$/, "Public"], [/^Ograniczony$/, "Restricted"], [/^Nieznany$/, "Unknown"],
    [/ · Godziny: /, " · Hours: "], [/^Szafka AED: /, "AED cabinet: "], [/^Szafka: /, "Cabinet: "], [/^Stan zamka: /, "Cabinet lock: "], [/^Wskazówki: /, "Directions: "], [/^Dysponent: /, "Operator: "], [/^Źródła: /, "Sources: "],
    [/^Lokalizacja · sprawdzono: /, "Location checked: "], [/^Dostęp · sprawdzono: /, "Access checked: "], [/^Sprawność · sprawdzono: /, "Readiness checked: "], [/brak daty/g, "unknown date"], [/^Sprawność: nieznana$/, "Readiness: unknown"], [/^Sprawność: potwierdzona na dzień kontroli$/, "Readiness: reported ready on check date"], [/^Sprawność: zgłoszono niesprawność$/, "Readiness: reported not ready"],
    [/WYSOKA PEWNOŚĆ/g,"HIGH SELF ASSESSMENT"], [/ŚREDNIA PEWNOŚĆ/g,"MEDIUM SELF ASSESSMENT"], [/NISKA \/ ORIENTACYJNA/g,"LOW / APPROXIMATE"], [/OCENA ZGŁASZAJĄCEGO/g,"SELF ASSESSMENT"], [/Wysoka pewność/g,"High evidence"], [/Średnia pewność/g,"Medium evidence"], [/Niska pewność/g,"Low evidence"],
    [/^Podaj poprawne współrzędne liczbowe WGS84\.$/,"Enter valid coordinates within Poland."], [/^Wybierz plik .geojson, .json lub .csv do zaimportowania\.$/,"Choose a GeoJSON, JSON or CSV file to import."], [/^Błąd importu: /,"Import error: "],
  ];
  let lang; try { lang = localStorage.getItem("aed-language") || "pl"; } catch { lang = "pl"; }
  const originals = new WeakMap();
  function translate(value) {
    const trimmed = value.trim();
    if (!trimmed || lang !== "en") return value;
    let translated = words[trimmed];
    if (!translated) { translated = trimmed; for (const [pattern, replacement] of patterns) translated = translated.replace(pattern, replacement); }
    return value.replace(trimmed, translated);
  }
  function apply(root = document.body) {
    observer.disconnect();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement?.closest("script,style,code,.leaflet-tile-pane")) continue;
      let state = originals.get(node);
      if (!state || (node.nodeValue !== state.rendered && node.nodeValue !== state.original)) state = {original:node.nodeValue};
      state.rendered = translate(state.original); originals.set(node, state);
      if (node.nodeValue !== state.rendered) node.nodeValue = state.rendered;
    }
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-lang]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.lang === lang)));
    document.querySelectorAll("input[placeholder]").forEach(input => { input.dataset.plPlaceholder ||= input.placeholder; input.placeholder = translate(input.dataset.plPlaceholder); });
    observer.observe(document.body, {subtree:true,childList:true,characterData:true});
  }
  let pending = false;
  const observer = new MutationObserver(() => { if (!pending) { pending=true; queueMicrotask(() => {pending=false;apply();}); } });
  document.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click", () => {lang=button.dataset.lang;try{localStorage.setItem("aed-language",lang);}catch{}apply();}));
  window.aedLanguage = {get current(){return lang;}, refresh:apply};
  apply();
})();
