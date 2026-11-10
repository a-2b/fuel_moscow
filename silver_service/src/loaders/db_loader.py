from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from shared.db import DimBrand, DimFuelType, SilverAzsGeo, SilverFuelPrice, SilverFuelAvailability

class SilverDataLoader:
    def __init__(self, session: Session):
        self.session = session

    def upsert_brand(self, brand_name: str, segment: str) -> int:
        """Идемпотентная вставка справочника брендов по уникальному имени"""
        stmt = insert(DimBrand).values(name=brand_name, segment=segment)
        
        # Конфликт по уникальному полю name
        stmt = stmt.on_conflict_do_update(
            index_elements=['name'],
            set_=dict(segment=stmt.excluded.segment)
        )
        # Выполняем и возвращаем PK (id)
        result = self.session.execute(stmt)
        return result.inserted_primary_key[0]

    def upsert_fuel_type(self, fuel_name: str) -> int:
        """Идемпотентная вставка справочника типов топлива"""
        stmt = insert(DimFuelType).values(name=fuel_name)
        
        stmt = stmt.on_conflict_do_update(
            index_elements=['name'],
            set_=dict(name=stmt.excluded.name)
        )
        result = self.session.execute(stmt)
        return result.inserted_primary_key[0]

    def upsert_azs(self, azs_id: int, brand_id: int, address: str, location_wkt: str):
        """Идемпотентная вставка объекта АЗС по первичному ключу (id)"""
        stmt = insert(SilverAzsGeo).values(
            id=azs_id,
            brand_id=brand_id,
            address=address,
            location=location_wkt
        )
        
        # Конфликт по PK (id)
        stmt = stmt.on_conflict_do_update(
            index_elements=['id'],
            set_=dict(
                brand_id=stmt.excluded.brand_id,
                address=stmt.excluded.address,
                location=stmt.excluded.location
            )
        )
        self.session.execute(stmt)

    def upsert_fuel_price(self, price_id: int, azs_id: int, fuel_type_id: int, price: float, timestamp):
        """Идемпотентная вставка факта цены по первичному ключу (id)"""
        stmt = insert(SilverFuelPrice).values(
            id=price_id,
            azs_id=azs_id,
            fuel_type_id=fuel_type_id,
            price=price,
            timestamp=timestamp
        )
        
        stmt = stmt.on_conflict_do_update(
            index_elements=['id'],
            set_=dict(
                price=stmt.excluded.price,
                timestamp=stmt.excluded.timestamp
            )
        )
        self.session.execute(stmt)

    def process_raw_data(self, raw_data_list: list):
        """Оркестрация загрузки пакета данных"""
        for row in raw_data_list:
            # 1. Загрузка измерений (Справочники)
            brand_id = self.upsert_brand(row['brand_name'], row['segment'])
            
            # 2. Загрузка объектов
            self.upsert_azs(row['azs_id'], brand_id, row['address'], row['location_wkt'])
            
            # 3. Загрузка фактов
            for fuel_name, price_val in row['prices'].items():
                fuel_type_id = self.upsert_fuel_type(fuel_name)
                
                # Генерация детерминированного ID факта на основе azs_id, fuel_type_id и времени (или получение из источника)
                fact_id = int(f"{row['azs_id']}{fuel_type_id}{int(row['timestamp'].timestamp())}")
                
                self.upsert_fuel_price(
                    price_id=fact_id,
                    azs_id=row['azs_id'],
                    fuel_type_id=fuel_type_id,
                    price=price_val,
                    timestamp=row['timestamp']
                )
        
        self.session.commit()