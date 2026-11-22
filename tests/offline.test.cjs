const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const memory = new Map();
const context = vm.createContext({window:{},navigator:{},localStorage:{getItem:key=>memory.get(key)||null,setItem:(key,value)=>memory.set(key,value)},Blob,Response,console});
vm.runInContext(fs.readFileSync('static/offline.js','utf8'),context);
const api = context.window.offlineData;
const plain = value => JSON.parse(JSON.stringify(value));
const row = {aed_id:'test-001',site_name:'Szkoła, wejście\n"A"',municipality:'Marki',latitude:52.32,longitude:21.1,source_ids:['municipality'],field_sources:{coordinates:'municipality'},is_stale:false};
(async()=>{
  const normalized=api.normalizeItem(row);
  for(const key of ['access_type','cabinet_lock_status','readiness_status','device_type']) assert.equal(normalized[key],'unknown');
  for(const key of ['opening_hours','location_checked_on','access_checked_on','readiness_checked_on','coordinate_accuracy_m','level']) assert.equal(normalized[key],null);
  const absent=api.normalizeItem({aed_id:'address',site_name:'Address',municipality:'Krosno',latitude:null,longitude:null,is_stale:'false'});
  assert.equal(absent.coordinate_status,'address_only'); assert.equal(absent.latitude,null); assert.equal(absent.is_stale,false);
  const json=api.toCanonicalJSON([row,absent]);
  const jsonImport=await api.parseImportText(JSON.stringify(json),'test.json');
  assert.equal(jsonImport.length,2); assert.equal(jsonImport[1].coordinate_status,'address_only');
  const csv=api.toCanonicalCSV([row]);
  const csvImport=await api.parseImportText(csv,'test.csv');
  assert.equal(csvImport[0].site_name,row.site_name); assert.deepEqual(plain(csvImport[0].source_ids),['municipality']);
  const geo=api.toCanonicalGeoJSON([row,absent]);
  assert.equal(geo.features.length,1); assert.equal(geo.metadata.address_only_omitted,1);
  const geoImport=await api.parseImportText(JSON.stringify(geo),'test.geojson');
  assert.equal(geoImport[0].longitude,21.1); assert.equal(geoImport[0].latitude,52.32);
  assert.equal(geoImport[0].readiness_status,'unknown');
  for(const bad of [
    [{...row,latitude:''}], [{...row,latitude:100}], [{...row,aed_id:''}], [row,row],
    [{...row,readiness_status:'maybe'}], [{...row,access_checked_on:'2026-02-31'}],
  ]) await assert.rejects(()=>api.parseImportText(JSON.stringify(bad)));
  await assert.rejects(()=>api.parseImportText(JSON.stringify({type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'LineString',coordinates:[]},properties:row}]})));
  const saved=api.addOrUpdateTag(row); assert.equal(saved.length,1); assert.equal(api.getTags()[0].is_user_tagged,true);
  api.addOrUpdateTag({...row,placement:'Entrance'}); assert.equal(api.getTags().length,1);
  await api.write('pack',{items:[row]}); assert.equal((await api.read()).items.length,1);
  assert.equal(api.toCanonicalCSV([{...row,site_name:'=HYPERLINK("x")'}]).includes("'=HYPERLINK"),true);
  console.log('Offline canonical roundtrip, unknown evidence, storage, CSV multiline and import validation: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
