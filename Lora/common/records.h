#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <math.h>
#include "config.h"
struct Site { String id, name, note; double lat=0, lon=0; uint32_t seen=0; };
inline bool cleanText(JsonVariantConst v, size_t limit) {
  if (!v.is<const char*>()) return false;
  const char* s = v.as<const char*>();
  size_t n = strlen(s);
  if (v.as<JsonString>().size() != n || !n || n > limit) return false;
  for (size_t i=0; i<n; ++i) if (s[i]<32 || s[i]>126) return false;
  return true;
}
inline bool decode(const String& wire, Site& s) {
  if (wire.length()>MAX_PACKET) return false;
  JsonDocument d;
  if (deserializeJson(d, wire) || !d["v"].is<int>() || d["v"].as<int>() != 1 ||
      !cleanText(d["id"],32) || !cleanText(d["n"],40) || !cleanText(d["p"],60) ||
      !d["lat"].is<double>() || !d["lon"].is<double>() || !d["a"].is<const char*>() || strcmp(d["a"].as<const char*>(), "unverified") != 0) return false;
  double lat=d["lat"], lon=d["lon"];
  if (!isfinite(lat)||!isfinite(lon)||lat<53.0||lat>53.3||lon<17.8||lon>18.3) return false;
  s.id=d["id"].as<String>(); s.name=d["n"].as<String>(); s.note=d["p"].as<String>();
  s.lat=lat; s.lon=lon; s.seen=millis();
  return true;
}
inline double distanceM(const Site& s) {
  double p=PI/180, a=sin((s.lat-ORIGIN_LAT)*p/2), b=sin((s.lon-ORIGIN_LON)*p/2);
  double h=a*a+cos(ORIGIN_LAT*p)*cos(s.lat*p)*b*b;
  return 12742000*asin(sqrt(fmin(1.0,h)));
}
struct SiteList {
  Site sites[MAX_SITES]; size_t count=0;
  bool add(const String& wire) {
    Site s; if (!decode(wire,s)) return false;
    size_t i=0;
    for (;i<count;++i) if(sites[i].id==s.id) break;
    if (i==count) {
      if (count<MAX_SITES) ++count;
      else { i=0; for(size_t j=1;j<count;++j) if(uint32_t(millis()-sites[j].seen)>uint32_t(millis()-sites[i].seen)) i=j; }
    }
    sites[i]=s;
    for(size_t a=0;a<count;++a) for(size_t b=a+1;b<count;++b)
      if(distanceM(sites[b])<distanceM(sites[a])) { Site t=sites[a]; sites[a]=sites[b]; sites[b]=t; }
    return true;
  }
};
