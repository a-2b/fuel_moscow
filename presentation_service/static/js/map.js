document.addEventListener('DOMContentLoaded', function () {
    // 1. Инициализация карты с центром в Москве и плагином полноэкранного режима
    const map = L.map('map_container', {
        fullscreenControl: true
    }).setView([55.751244, 37.618423], 10);

    // 2. Стабильный светлый тайловый слой CartoDB Positron (на базе данных OpenStreetMap)
    // Возвращаем стандартную детальную цветную карту OpenStreetMap
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    let geoJsonLayer = null;
    let allFeatures = [];
    let activeFuel = null;
    let activePriceMode = null;

    // 3. Палитра фирменных пастельных цветов сетей
    const brandColors = {
        'РОСНЕФТЬ': '#f6ad55',
        'РОСПИРТЬ': '#f6ad55', // Страховочный алиас
        'ЛУКОЙЛ': '#fc8181',
        'ГАЗПРОМНЕФТЬ': '#63b3ed',
        'ТАТНЕФТЬ': '#4fd1c5',
        'ТЕБОЙЛ': '#f687b3',
        'НЕФТЬМАГИСТРАЛЬ': '#68d391',
        'default': '#a0aec0'
    };

    // Нормализация наименования бренда
    function normalizeBrand(rawBrand) {
        if (!rawBrand) return 'Роснефть';
        const str = String(rawBrand).trim();
        if (str.toUpperCase().includes('РОСПИРТ')) {
            return 'Роснефть';
        }
        return str;
    }

    // Регистронезависимый поиск цвета бренда
    function getBrandColor(brand) {
        const cleanBrand = normalizeBrand(brand).toUpperCase();
        for (const [key, color] of Object.entries(brandColors)) {
            if (key !== 'default' && cleanBrand.includes(key)) {
                return color;
            }
        }
        return brandColors['default'];
    }

    // Извлечение цены топлива
    function extractPrice(p, fuelKey) {
        if (!p || !p.prices) return null;
        const val = p.prices[fuelKey];
        if (val !== undefined && val !== null && !isNaN(parseFloat(val))) {
            return parseFloat(val);
        }
        return null;
    }

    // Извлечение уровня запасов топлива
    function extractAvail(p, fuelKey) {
        if (!p || !p.availability) return 100;
        const val = p.availability[fuelKey];
        if (val !== undefined && val !== null && !isNaN(parseInt(val, 10))) {
            return parseInt(val, 10);
        }
        return 0;
    }

    // Всплывающее предупреждение при незаполненных фильтрах
    function showWarning(text) {
        let banner = document.getElementById('fuel-alert-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'fuel-alert-banner';
            banner.style.position = 'fixed';
            banner.style.top = '25px';
            banner.style.right = '25px';
            banner.style.backgroundColor = '#e53e3e';
            banner.style.color = '#ffffff';
            banner.style.padding = '12px 24px';
            banner.style.borderRadius = '8px';
            banner.style.boxShadow = '0 4px 15px rgba(0,0,0,0.15)';
            banner.style.zIndex = '10000';
            banner.style.fontWeight = '600';
            banner.style.fontSize = '13.5px';
            banner.style.fontFamily = 'Segoe UI, sans-serif';
            banner.style.transition = 'all 0.3s ease';
            document.body.appendChild(banner);
        }
        banner.textContent = text;
        banner.style.opacity = '1';
        banner.style.display = 'block';
        clearTimeout(banner._timer);
        banner._timer = setTimeout(() => {
            banner.style.opacity = '0';
            setTimeout(() => { banner.style.display = 'none'; }, 300);
        }, 3000);
    }

    // 4. Отрисовка маркеров станций
    function renderMarkers(features, autoOpenFirst = false) {
        if (geoJsonLayer) {
            map.removeLayer(geoJsonLayer);
        }

        let firstLayer = null;

        geoJsonLayer = L.geoJSON({
            type: 'FeatureCollection',
            features: features
        }, {
            pointToLayer: function (feature, latlng) {
                const brand = normalizeBrand(feature.properties.brand);
                return L.circleMarker(latlng, {
                    radius: activePriceMode ? 9 : 6.5,
                    fillColor: getBrandColor(brand),
                    color: '#ffffff',
                    weight: activePriceMode ? 2.5 : 1.5,
                    opacity: 1,
                    fillOpacity: 0.95
                });
            },
            onEachFeature: function (feature, layer) {
                if (!firstLayer) firstLayer = layer;
                const p = feature.properties;
                
                // Получаем реальный адрес из БД без условных улиц
                const cleanAddress = p.address || p.addr || 'г. Москва';

                const cleanBrand = normalizeBrand(p.brand);
                const brandColor = getBrandColor(cleanBrand);

                const p92 = extractPrice(p, 'AI-92');
                const p95 = extractPrice(p, 'AI-95');
                const pdt = extractPrice(p, 'DT');
                const a92 = extractAvail(p, 'AI-92');
                const a95 = extractAvail(p, 'AI-95');
                const adt = extractAvail(p, 'DT');

                // Всплывающее окно: 1 строка — реальный адрес, 2 строка — оператор
                const popupHtml = `
                    <div style="min-width: 220px; font-family: Segoe UI, -apple-system, sans-serif; color: #2d3748;">
                        <div style="font-size: 13.5px; font-weight: 700; color: #1a202c; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px; margin-bottom: 5px; line-height: 1.35;">
                            ${cleanAddress}
                        </div>
                        <div style="font-size: 12px; margin-bottom: 8px; color: #718096;">
                            Оператор: <strong style="color: ${brandColor}; font-weight: 700;">${cleanBrand}</strong>
                        </div>
                        <div style="border-top: 1px solid #edf2f7; padding-top: 6px; font-size: 12.5px;">
                            <div style="display: flex; justify-content: space-between; margin: 3px 0; ${activeFuel === 'AI-92' ? 'background: #ebf8ff; padding: 2px 5px; border-radius: 4px; font-weight: 700;' : ''}">
                                <span>АИ-92:</span> 
                                <span>${p92 !== null ? p92.toFixed(2) + ' ₽' : '—'} <small style="color: #a0aec0;">(${a92}%)</small></span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin: 3px 0; ${activeFuel === 'AI-95' ? 'background: #ebf8ff; padding: 2px 5px; border-radius: 4px; font-weight: 700;' : ''}">
                                <span>АИ-95:</span> 
                                <span>${p95 !== null ? p95.toFixed(2) + ' ₽' : '—'} <small style="color: #a0aec0;">(${a95}%)</small></span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin: 3px 0; ${activeFuel === 'DT' ? 'background: #ebf8ff; padding: 2px 5px; border-radius: 4px; font-weight: 700;' : ''}">
                                <span>ДТ:</span> 
                                <span>${pdt !== null ? pdt.toFixed(2) + ' ₽' : '—'} <small style="color: #a0aec0;">(${adt}%)</small></span>
                            </div>
                        </div>
                    </div>
                `;
                layer.bindPopup(popupHtml);
            }
        }).addTo(map);

        if (autoOpenFirst && firstLayer) {
            firstLayer.openPopup();
            map.panTo(firstLayer.getLatLng());
        }

        setTimeout(() => { map.invalidateSize(); }, 200);
    }

    // 5. Загрузка данных пространственного среза
    fetch('/api/map-data')
        .then(response => {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        })
        .then(data => {
            allFeatures = Array.isArray(data) ? data : (data.features || []);
            renderMarkers(allFeatures);
        })
        .catch(err => console.error('Ошибка загрузки данных карты:', err));

    // 6. Логика панели Smart-фильтрации
    function applyFilters() {
        let result = allFeatures;

        // Фильтрация по виду топлива (цена существует и запасы > 0%)
        if (activeFuel) {
            result = result.filter(f => {
                const price = extractPrice(f.properties, activeFuel);
                const avail = extractAvail(f.properties, activeFuel);
                return price !== null && avail > 0;
            });
        }

        // Фильтрация по экстремальным ценам (min / max)
        if (activeFuel && activePriceMode) {
            const prices = result
                .map(f => extractPrice(f.properties, activeFuel))
                .filter(p => p !== null);

            if (prices.length > 0) {
                const targetPrice = activePriceMode === 'min' ? Math.min(...prices) : Math.max(...prices);
                result = result.filter(f => {
                    const p = extractPrice(f.properties, activeFuel);
                    return p !== null && Math.abs(p - targetPrice) < 0.001;
                });
            }
        }

        renderMarkers(result, !!activePriceMode);
    }

    window.toggleFuel = function (fuelType) {
        const btnMap = { 'AI-92': 'btn-ai92', 'AI-95': 'btn-ai95', 'DT': 'btn-dt' };
        const btn = document.getElementById(btnMap[fuelType]);

        if (activeFuel === fuelType) {
            activeFuel = null;
            if (btn) btn.classList.remove('active');
            activePriceMode = null;
            document.querySelectorAll('.btn-sort').forEach(b => b.classList.remove('active'));
        } else {
            document.querySelectorAll('.btn-fuel').forEach(b => b.classList.remove('active'));
            activeFuel = fuelType;
            if (btn) btn.classList.add('active');
        }

        applyFilters();
    };

    window.togglePrice = function (type) {
        if (!activeFuel) {
            showWarning('Сначала выберите вид топлива (АИ-92, АИ-95 или ДТ)');
            return;
        }

        const btn = document.getElementById(type === 'min' ? 'btn-pmin' : 'btn-pmax');

        if (activePriceMode === type) {
            activePriceMode = null;
            if (btn) btn.classList.remove('active');
        } else {
            document.querySelectorAll('.btn-sort').forEach(b => b.classList.remove('active'));
            activePriceMode = type;
            if (btn) btn.classList.add('active');
        }

        applyFilters();
    };
});