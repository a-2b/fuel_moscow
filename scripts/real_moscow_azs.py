import json
import urllib.parse
import urllib.request

# Запрос к Overpass API на поиск всех АЗС внутри границ Москвы
overpass_url = "https://overpass-api.de/api/interpreter"
overpass_query = """
[out:json][timeout:30];
area["ISO3166-2"="RU-MOW"][admin_level=4]->.moscow;
(
  node["amenity"="fuel"](area.moscow);
  way["amenity"="fuel"](area.moscow);
);
out center tags;
"""

print("Запрос реальных АЗС Москвы из OpenStreetMap...")
req = urllib.request.Request(
    overpass_url,
    data=urllib.parse.urlencode({'data': overpass_query}).encode('utf-8'),
    headers={'User-Agent': 'MoscowFuelETL/1.0'}
)

with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode('utf-8'))

stations = []
for el in data.get('elements', []):
    tags = el.get('tags', {})
    
    # Координаты (для way берем вычисленный центр)
    lat = el.get('lat') or el.get('center', {}).get('lat')
    lon = el.get('lon') or el.get('center', {}).get('lon')
    
    # Бренд / оператор
    brand = tags.get('brand') or tags.get('operator') or tags.get('name') or 'Независимая АЗС'
    
    # Адрес из тегов OSM
    street = tags.get('addr:street', '')
    house = tags.get('addr:housenumber', '')
    
    if street:
        address = f"г. Москва, {street}" + (f", д. {house}" if house else "")
    else:
        address = tags.get('name', f"АЗС на трассе ({lat:.4f}, {lon:.4f})")
    
    if lat and lon:
        stations.append({
            "osm_id": el.get('id'),
            "brand": brand,
            "address": address,
            "lat": lat,
            "lon": lon
        })

print(f"Успешно выгружено {len(stations)} реальных АЗС!")
with open("real_moscow_azs.json", "w", encoding="utf-8") as f:
    json.dump(stations, f, ensure_ascii=False, indent=2)

print("Данные сохранены в real_moscow_azs.json")