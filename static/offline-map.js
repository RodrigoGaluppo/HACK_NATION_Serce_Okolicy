"use strict";
// A small, explicit vector pack; never prefetches remote map tiles.
window.AEDOfflineMap = (() => {
  let map, detail, coverage, labels, saved, section, status, offline = !navigator.onLine;
  const maxBytes = 30 * 1024 * 1024;
  function validate(pack) {
    if (!pack || pack.type !== "FeatureCollection" || !Array.isArray(pack.features) || !pack.features.length || pack.features.length > 30000) throw new Error("Paczka mapy wymaga 1–30 000 obiektów GeoJSON.");
    const c = pack.metadata?.center;
    const lat = Number(c?.lat ?? c?.latitude), lon = Number(c?.lon ?? c?.lng ?? c?.longitude);
    const radius = Number(pack.metadata?.radius_km ?? pack.metadata?.radius);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 48 || lat > 56 || lon < 13 || lon > 25 || !Number.isFinite(radius) || radius <= 0 || radius > 3) throw new Error("Paczka wymaga środka w Polsce i promienia do 3 km.");
    let coordinates = 0;
    const point = (p) => {
      if (!Array.isArray(p) || p.length < 2 || !p.slice(0,2).every(n=>typeof n === "number" && Number.isFinite(n)) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) throw new Error("Nieprawidłowe współrzędne mapy.");
      if (Math.abs(p[0]-lon)>0.3 || Math.abs(p[1]-lat)>0.2) throw new Error("Geometria poza obszarem pobranej mapy.");
      if (++coordinates > 600000) throw new Error("Paczka zawiera zbyt wiele współrzędnych.");
    };
    for (const feature of pack.features) {
      if (feature.type !== "Feature" || !feature.geometry) throw new Error("Nieprawidłowy obiekt mapy.");
      const g=feature.geometry;
      if (g.type === "LineString" || g.type === "MultiPoint") g.coordinates.forEach(point);
      else if (g.type === "Polygon" || g.type === "MultiLineString") g.coordinates.forEach(ring=>ring.forEach(point));
      else if (g.type === "MultiPolygon") g.coordinates.forEach(poly=>poly.forEach(ring=>ring.forEach(point)));
      else if (g.type === "Point") point(g.coordinates);
      else throw new Error("Nieobsługiwana geometria mapy.");
    }
    return {...pack,metadata:{...pack.metadata,center:{lat,lon},radius_km:radius,attribution:"© OpenStreetMap contributors · ODbL"}};
  }
  function tags(feature) {return feature.properties?.tags || feature.properties || {};}
  function style(feature) {
    const t=tags(feature); const road=t.highway || t.kind === "road" || t.type === "road";
    if (road) return {color:["motorway","trunk","primary"].includes(t.highway)?"#d5b475":"#d8cfb8",weight:["motorway","trunk","primary","secondary"].includes(t.highway)?4:2,opacity:1};
    if (t.building || t.kind === "building" || t.type === "building") return {color:"#b4bdae",weight:0.7,fillColor:"#d2d9c9",fillOpacity:0.85};
    return {color:"#83afba",weight:2,fillColor:"#b7d6dc",fillOpacity:0.8};
  }
  function render() {
    if (!map) return;
    if (detail) map.removeLayer(detail); if (coverage) map.removeLayer(coverage); if (labels) map.removeLayer(labels);
    if (!saved) return;
    const renderer=L.canvas({pane:"offlineDetail",padding:0.25});
    detail=L.geoJSON(saved,{pane:"offlineDetail",renderer,interactive:false,style,pointToLayer:(_,latlng)=>L.circleMarker(latlng,{pane:"offlineDetail",renderer,radius:2,interactive:false,color:"#83afba"})});
    labels=L.layerGroup();
    const names=new Set(), labelPositions=[];
    for (const feature of saved.features) {
      const t=tags(feature), g=feature.geometry;
      if (!t.highway || ["service","footway","path","steps","cycleway","track"].includes(t.highway) || typeof t.name !== "string" || names.has(t.name) || names.size >= 70 || g.type !== "LineString" || !g.coordinates.length) continue;
      const p=g.coordinates[Math.floor(g.coordinates.length/2)], projected=map.project([p[1],p[0]],16);
      if(labelPositions.some(existing=>existing.distanceTo(projected)<75))continue;
      names.add(t.name);labelPositions.push(projected);
      const text=document.createElement("span");text.textContent=t.name;
      L.tooltip({permanent:true,direction:"center",className:"offline-road-name",opacity:0.95}).setLatLng([p[1],p[0]]).setContent(text).addTo(labels);
    }
    const c=saved.metadata.center;
    coverage=L.circle([c.lat,c.lon],{pane:"offlineDetail",radius:saved.metadata.radius_km*1000,color:"#557647",weight:1,dashArray:"5 5",fill:false,interactive:false});
    // Local detail is useful online too; remote streets stay above it while online.
    if (offline) {detail.addTo(map); coverage.addTo(map); if(map.getZoom() >= 15)labels.addTo(map);}
    const label=section?.querySelector('[data-map-coverage]');
    if (label) label.textContent=`Zapisano ${saved.features.length} obiektów · ${saved.metadata.radius_km} km wokół ${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}. Szczegóły ulic są dostępne wyłącznie w tym obszarze. © OpenStreetMap contributors · ODbL`;
  }
  function download(content,name) {
    const url=URL.createObjectURL(new Blob([content],{type:"application/geo+json"}));const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);
  }
  async function save(pack) {const normalized=validate(pack);await window.offlineData.write("basemap",normalized);saved=normalized;render();}
  function createControls() {
    const hub=document.querySelector("#offline-dialog .dialog-grid");if(!hub)return;
    section=document.createElement("section");section.className="dialog-box";
    section.innerHTML='<h3>Ulice i budynki offline</h3><p>Pobierz małą mapę wokół środka widoku. Ulice, budynki i woda działają lokalnie w zapisanym obszarze. Bez wyznaczania trasy.</p><div class="inline-controls"><label>Promień mapy <select data-map-radius aria-label="Promień szczegółowej mapy"><option value="0.5">0,5 km</option><option value="1">1 km</option><option value="2">2 km</option><option value="3">3 km</option></select></label><button type="button" class="button primary" data-map-save>Pobierz mapę ulic</button><button type="button" class="button secondary" data-map-export>Eksportuj mapę</button></div><label style="display:block;margin-top:12px">Import mapy (.map.geojson)<input type="file" data-map-import accept=".geojson,.json,application/geo+json,application/json"></label><p class="status-note" data-map-status role="status"></p><p class="status-note" data-map-coverage>Brak pobranej mapy ulic. Uproszczona mapa Polski jest już dostępna offline.</p>';
    hub.append(section);status=section.querySelector('[data-map-status]');
    section.querySelector('[data-map-save]').addEventListener('click',async(event)=>{
      if(!navigator.onLine){status.textContent="Pobranie nowego obszaru wymaga internetu. Możesz zaimportować zapisany plik mapy.";return;}
      const button=event.currentTarget;button.disabled=true;status.textContent="Pobieranie mapy ulic i budynków…";
      try {
        const c=map.getCenter();const params=new URLSearchParams({lat:c.lat,lon:c.lng,radius_km:section.querySelector('[data-map-radius]').value});
        const response=await fetch('/api/map-pack?'+params,{signal:AbortSignal.timeout(65000)});
        if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.error || "Źródło mapy jest chwilowo niedostępne.");}
        const body=await response.text();if(new Blob([body]).size>maxBytes)throw new Error("Mapa przekracza limit 30 MB. Wybierz mniejszy obszar.");
        await save(JSON.parse(body));status.textContent="Mapa zapisana na tym urządzeniu. W trybie offline pojawią się pobrane ulice i budynki.";
      }catch(error){status.textContent="Nie zapisano mapy: "+error.message;}finally{button.disabled=false;}
    });
    section.querySelector('[data-map-export]').addEventListener('click',()=>{if(!saved){status.textContent="Najpierw pobierz lub zaimportuj mapę.";return;}download(JSON.stringify(saved),'serce-okolicy.map.geojson');});
    section.querySelector('[data-map-import]').addEventListener('change',async(event)=>{
      const file=event.target.files?.[0];if(!file)return;
      try{if(file.size>maxBytes)throw new Error("Limit pliku mapy: 30 MB.");await save(JSON.parse(await file.text()));status.textContent="Mapa zaimportowana lokalnie. Połączenie z serwerem nie było potrzebne.";}
      catch(error){status.textContent="Błąd importu mapy: "+error.message;}
      event.target.value="";
    });
  }
  return {
    async init(instance) {
      if(map)return;map=instance;map.createPane('offlineDetail').style.zIndex=180;createControls();
      const css=document.createElement('style');css.textContent='.offline-road-name{background:transparent;border:0;box-shadow:none;color:#425343;font:500 10px sans-serif;text-shadow:0 1px #fff,1px 0 #fff,-1px 0 #fff;pointer-events:none}.offline-road-name:before{display:none}';document.head.append(css);
      map.on('zoomend',()=>{if(!labels)return;if(offline&&map.getZoom()>=15)labels.addTo(map);else map.removeLayer(labels);});
      map.attributionControl.addAttribution('Offline streets: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>');
      try{const pack=await window.offlineData.read('basemap');if(pack)saved=validate(pack);render();}catch{if(status)status.textContent="Zapisana mapa jest nieprawidłowa. Pobierz ją ponownie.";}
    },
    setOffline(value){const next=Boolean(value);if(next===offline)return;offline=next;render();},
    get hasSavedMap(){ return Boolean(saved); },
    validate,
  };
})();
