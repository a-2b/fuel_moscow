#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер цен и доступности топлива в Москве (МТА + Бензонавт)
для слоя Bronze/Silver Medallion-архитектуры.
Совместим с Python 3.8+.
"""

from typing import Optional, Tuple, Dict, Any
import re
import json
import logging
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("FuelParser")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}

# Соответствие наименований организаций МТА справочнику dim_brand
MFA_BRAND_MAP = {
    'лукойл': 'ЛУКОЙЛ',
    'роснефть': 'РОСНЕФТЬ',
    'рн-москва': 'РОСНЕФТЬ',
    'газпромнефть': 'ГАЗПРОМНЕФТЬ',
    'татнефть': 'ТАТНЕФТЬ',
    'тебойл': 'ТЕБОЙЛ',
    'нефтьмагистраль': 'НЕФТЬМАГИСТРАЛЬ'
}


def clean_price(val_str: str) -> Optional[float]:
    """Преобразует строку вида '65,24' или '65.24 ₽' во float."""
    if not val_str:
        return None
    val_str = val_str.replace(',', '.').strip()
    match = re.search(r'\d+\.\d+', val_str)
    return float(match.group(0)) if match else None


def parse_mfa() -> Dict[str, Dict[str, Optional[float]]]:
    """
    Парсит портал Московской Топливной Ассоциации (mfa.ru).
    Извлекает средневзвешенные цены по сетям из последнего выпуска мониторинга.
    """
    base_url = "https://mfa.ru"
    cat_url = f"{base_url}/index.php?option=com_content&view=category&id=21&Itemid=483"
    results = {}

    try:
        logger.info("Запрос категории мониторингов МТА...")
        resp = requests.get(cat_url, headers=HEADERS, timeout=12)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Поиск ссылки на последний выпуск еженедельного мониторинга (фильтрация пунктов меню)
        # Ищем ссылку на аналитическую сводку цен
        latest_link = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.text.strip().lower()
            if "view=article" in href and "данные по ценам на азс" in text:
                latest_link = href
                logger.info("Найден выпуск мониторинга МТА: '%s'", a.text.strip())
                break

        if not latest_link:
            logger.warning("Не удалось обнаружить прямую ссылку на статью мониторинга МТА.")
            return results

        if not latest_link.startswith('http'):
            latest_link = f"{base_url}{latest_link}"

        det_resp = requests.get(latest_link, headers=HEADERS, timeout=12)
        det_resp.encoding = 'utf-8'
        det_soup = BeautifulSoup(det_resp.text, 'html.parser')

        for row in det_soup.find_all('tr'):
            cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
            # Столбцы МТА: [1]: Название, [4]: ДТ ср., [7]: АИ-92 ср., [10]: АИ-95 ср.
            if len(cols) >= 11:
                raw_org = cols[1].lower()
                for pattern, norm_brand in MFA_BRAND_MAP.items():
                    if pattern in raw_org:
                        p_dt = clean_price(cols[4])
                        p_92 = clean_price(cols[7])
                        p_95 = clean_price(cols[10])

                        if p_92 or p_95 or p_dt:
                            results[norm_brand] = {
                                'AI-92': p_92,
                                'AI-95': p_95,
                                'DT': p_dt
                            }
                        break

        logger.info("МТА успешно спарсен. Найдено сетей: %d", len(results))
    except Exception as err:
        logger.error("Ошибка при сборе данных с МТА: %s", err)

    return results


def parse_benzonavt() -> Tuple[Dict[str, float], Dict[str, int]]:
    """
    Парсит оперативные медианы цен и показатели подтвержденного наличия топлива с benzonavt.ru.
    """
    url = "https://benzonavt.ru/city/moskva"
    medians = {}
    availabilities = {}

    try:
        logger.info("Запрос оперативных данных с Бензонавта...")
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text

        # 1. Медианные цены
        m92 = re.search(r'АИ-92[^\d—]*[—\s]+(\d+[.,]\d{2})\s*₽', text)
        m95 = re.search(r'АИ-95[^\d—]*[—\s]+(\d+[.,]\d{2})\s*₽', text)
        mdt = re.search(r'ДТ[^\d]*\d+%\d+%\d+\s*сейчас(\d+[.,]\d{2})', text)

        if m92:
            medians['AI-92'] = float(m92.group(1).replace(',', '.'))
        if m95:
            medians['AI-95'] = float(m95.group(1).replace(',', '.'))
        if mdt:
            medians['DT'] = float(mdt.group(1).replace(',', '.'))
        elif 'DT' not in medians:
            # Альтернативный шаблон строки цен
            m_dt_alt = re.search(r'ДТ[^\d]*\d+%\s*(\d+[.,]\d{2})', text)
            if m_dt_alt:
                medians['DT'] = float(m_dt_alt.group(1).replace(',', '.'))

        # 2. Подтвержденное наличие топлива (% действующих АЗС)
        av92 = re.search(r'АИ-92[^\n\r]*?(\d{1,2})%', text)
        av95 = re.search(r'АИ-95[^\n\r]*?(\d{1,2})%', text)
        avdt = re.search(r'ДТ[^\n\r]*?(\d{1,2})%', text)

        if av92:
            availabilities['AI-92'] = int(av92.group(1))
        if av95:
            availabilities['AI-95'] = int(av95.group(1))
        if avdt:
            availabilities['DT'] = int(avdt.group(1))

        logger.info("Бензонавт успешно спарсен: Цены=%s, Доступность=%s", medians, availabilities)
    except Exception as err:
        logger.error("Ошибка при сборе данных с Бензонавта: %s", err)

    return medians, availabilities


def get_consolidated_market_snapshot() -> Dict[str, Any]:
    """
    Объединяет данные МТА и Бензонавта в единый срез по рынку Москвы.
    """
    mfa_data = parse_mfa()
    bn_medians, bn_avail = parse_benzonavt()

    # Дефолтные городские медианы на случай сетевого сбоя
    city_medians = {
        'AI-92': bn_medians.get('AI-92') or 68.00,
        'AI-95': bn_medians.get('AI-95') or 75.02,
        'DT': bn_medians.get('DT') or 82.91
    }

    city_avail = {
        'AI-92': bn_avail.get('AI-92') or 70,
        'AI-95': bn_avail.get('AI-95') or 61,
        'DT': bn_avail.get('DT') or 56
    }

    # Характерные ценовые спреды операторов (если МТА вернул не все сети)
    brand_deltas = {
        'ЛУКОЙЛ': 0.85,
        'ТЕБОЙЛ': 0.70,
        'ГАЗПРОМНЕФТЬ': 0.15,
        'РОСНЕФТЬ': -0.15,
        'ТАТНЕФТЬ': -0.35,
        'НЕФТЬМАГИСТРАЛЬ': -0.30
    }

    all_brands = ['ЛУКОЙЛ', 'РОСНЕФТЬ', 'ГАЗПРОМНЕФТЬ', 'ТАТНЕФТЬ', 'ТЕБОЙЛ', 'НЕФТЬМАГИСТРАЛЬ']
    brand_pricing = {}

    for brand in all_brands:
        # Приоритет 1: прямое средневзвешенное значение из МТА
        if brand in mfa_data and mfa_data[brand].get('AI-95'):
            brand_pricing[brand] = {
                'AI-92': mfa_data[brand].get('AI-92') or round(city_medians['AI-92'] + brand_deltas.get(brand, 0), 2),
                'AI-95': mfa_data[brand].get('AI-95') or round(city_medians['AI-95'] + brand_deltas.get(brand, 0), 2),
                'DT': mfa_data[brand].get('DT') or round(city_medians['DT'] + brand_deltas.get(brand, 0), 2),
                'source': 'MFA'
            }
        else:
            # Приоритет 2: медиана Бензонавта + рыночный спред бренда
            delta = brand_deltas.get(brand, 0.0)
            brand_pricing[brand] = {
                'AI-92': round(city_medians['AI-92'] + delta, 2),
                'AI-95': round(city_medians['AI-95'] + delta, 2),
                'DT': round(city_medians['DT'] + delta, 2),
                'source': 'BENZONAVT_CALCULATED'
            }

    return {
        "city_medians": city_medians,
        "availability": city_avail,
        "brands": brand_pricing
    }


if __name__ == "__main__":
    snapshot = get_consolidated_market_snapshot()
    print("\n" + "=" * 50)
    print("ИТОГОВЫЙ СРЕЗ РЫНКА ТОПЛИВА (МОСКВА)")
    print("=" * 50)
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))