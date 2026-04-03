from __future__ import annotations

from typing import Any, List, Optional, Tuple, TypedDict


class SensorData(TypedDict):
    """Данные, поступающие от датчиков системы."""

    time: int               # Текущий час (0–23)
    solar_avail: bool       # Доступность солнечной энергии
    wind_strength: float    # Мощность ветра (0–100 %)
    battery_level: float    # Уровень заряда накопителя (0–100 %)
    hospital_demand: float  # Потребление больницы (0–100 %)
    school_demand: float    # Потребление школы (0–100 %)
    houses_demand: float    # Потребление жилых домов (0–100 %)
    factory_demand: float   # Потребление завода (0–100 %)


class SwitchState(TypedDict):
    """Состояние исполнительных ключей (True = включён, False = отключён)."""

    ges: bool         # ГЭС (не используется для цели энергоэффективности)
    solar: bool       # Солнечные панели
    wind: bool        # Ветрогенераторы
    battery: bool     # Накопитель энергии
    hospital: bool    # Больница
    school: bool      # Школа
    houses: bool      # Жилые дома
    factory: bool     # Завод


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

BATTERY_MIN_LEVEL = 20.0          # Минимальный допустимый заряд батареи (%)
BATTERY_DEEP_DISCHARGE = 10.0     # Критический уровень (глубокий разряд)
WIND_THRESHOLD_HIGH = 60.0        # Сильный ветер — можно питать всех
WIND_THRESHOLD_LOW = 30.0         # Слабый ветер — только приоритеты
SCHOOL_WORK_START = 8             # Начало рабочего времени школы
SCHOOL_WORK_END = 17              # Конец рабочего времени школы

# Диапазоны допустимых значений датчиков (для валидации в safe_control)
SENSOR_RANGES = {
    "time": (0, 23),
    "wind_strength": (0.0, 100.0),
    "battery_level": (0.0, 100.0),
    "hospital_demand": (0.0, 100.0),
    "school_demand": (0.0, 100.0),
    "houses_demand": (0.0, 100.0),
    "factory_demand": (0.0, 100.0),
}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _is_daytime(time: int) -> bool:
    """Возвращает True, если текущее время — дневное (6–20 ч)."""
    return 6 <= time <= 20



def _is_school_hours(time: int) -> bool:
    """Возвращает True, если школа работает."""
    return SCHOOL_WORK_START <= time < SCHOOL_WORK_END



def _has_sufficient_generation(solar: bool, wind: float, battery: float) -> str:
    """
    Оценивает уровень доступной генерации.
    Возвращает: 'high' | 'medium' | 'low'
    """
    if (solar and wind >= WIND_THRESHOLD_LOW) or wind >= WIND_THRESHOLD_HIGH:
        return "high"
    if solar or wind >= WIND_THRESHOLD_LOW or battery > BATTERY_MIN_LEVEL + 20:
        return "medium"
    return "low"



def _empty_state() -> SwitchState:
    """Возвращает безопасное значение по умолчанию для mypy и fallback-сценариев."""
    return {
        "ges": False,
        "solar": False,
        "wind": False,
        "battery": False,
        "hospital": False,
        "school": False,
        "houses": False,
        "factory": False,
    }


# ---------------------------------------------------------------------------
# Задача 1: штатный алгоритм управления
# ---------------------------------------------------------------------------


def control(sensors: SensorData) -> SwitchState:
    """
    Штатный алгоритм управления исполнительными ключами.

    Цели безопасности (в порядке приоритета):
      1. Бесперебойное питание больницы — ВСЕГДА включена.
      2. Питание школы в рабочее время при дефиците энергии.
      3. Защита накопителя от глубокого разряда и разряда без нагрузки.

    Политика использования ГЭС:
      ГЭС НЕ задействуется в обычном режиме (цель энергоэффективности).
      Включается ТОЛЬКО если иначе нельзя обеспечить работу больницы
      (аварийный fallback — в данной реализации не задействован).

    Параметры:
      sensors — словарь с показаниями датчиков (см. SensorData).

    Возвращает:
      Словарь состояний ключей (см. SwitchState).
    """
    time = sensors["time"]
    solar_avail = sensors["solar_avail"]
    wind_strength = sensors["wind_strength"]
    battery_level = sensors["battery_level"]

    generation = _has_sufficient_generation(solar_avail, wind_strength, battery_level)
    battery_usable = battery_level > BATTERY_DEEP_DISCHARGE

    solar_on = solar_avail and _is_daytime(time)
    wind_on = wind_strength >= WIND_THRESHOLD_LOW
    battery_on = battery_usable

    hospital_on = True
    school_on = _is_school_hours(time)

    if generation == "high":
        houses_on = True
        factory_on = True
    elif generation == "medium":
        houses_on = True
        factory_on = False
    else:
        houses_on = False
        factory_on = False

    any_consumer = hospital_on or school_on or houses_on or factory_on
    if not any_consumer:
        battery_on = False

    return {
        "ges": False,
        "solar": solar_on,
        "wind": wind_on,
        "battery": battery_on,
        "hospital": hospital_on,
        "school": school_on,
        "houses": houses_on,
        "factory": factory_on,
    }


# ---------------------------------------------------------------------------
# Задача 2: защищённый алгоритм при компрометации датчиков
# ---------------------------------------------------------------------------


def _validate_sensor(
    name: str,
    value: Any,
    expected_type: type[Any] | tuple[type[Any], ...],
    ranges: dict[str, tuple[float, float]],
) -> Tuple[bool, Optional[object]]:
    """
    Проверяет корректность значения датчика.
    Возвращает (is_valid, sanitized_value).
    """
    if not isinstance(value, expected_type):
        return False, None

    if name in ranges:
        lo, hi = ranges[name]
        if not (lo <= value <= hi):
            return False, None

    return True, value



def _sanitize_sensors(sensors: SensorData) -> Tuple[SensorData, List[str]]:
    """
    Валидирует и очищает входные данные датчиков.

    Возвращает:
      (sanitized, warnings) — очищенные данные и список предупреждений.
    """
    warnings: List[str] = []
    sanitized: dict[str, Any] = {}

    numeric_fields = [
        "time",
        "wind_strength",
        "battery_level",
        "hospital_demand",
        "school_demand",
        "houses_demand",
        "factory_demand",
    ]
    defaults = {
        "time": 12,
        "wind_strength": 0.0,
        "battery_level": 50.0,
        "hospital_demand": 100.0,
        "school_demand": 50.0,
        "houses_demand": 50.0,
        "factory_demand": 50.0,
    }

    for field in numeric_fields:
        if field not in sensors:
            warnings.append(f"Отсутствует датчик: {field}")
            sanitized[field] = defaults[field]
            continue

        value = sensors[field]
        if field != "time" and isinstance(value, int):
            value = float(value)

        expected_type: type[Any] | tuple[type[Any], ...]
        if field == "time":
            expected_type = int
        else:
            expected_type = (int, float)

        ok, clean = _validate_sensor(field, value, expected_type, SENSOR_RANGES)
        if ok:
            sanitized[field] = value
            continue

        warnings.append(f"Некорректное значение датчика {field}: {value!r}")
        if field == "battery_level":
            sanitized[field] = BATTERY_MIN_LEVEL
        elif field == "time":
            sanitized[field] = defaults[field]
        else:
            sanitized[field] = 0.0

    if "solar_avail" not in sensors:
        warnings.append("Отсутствует датчик: solar_avail")
        sanitized["solar_avail"] = False
    else:
        value = sensors["solar_avail"]
        if isinstance(value, bool):
            sanitized["solar_avail"] = value
        else:
            warnings.append(f"Некорректный тип solar_avail: {value!r}, ожидался bool")
            sanitized["solar_avail"] = bool(value)

    return SensorData(**sanitized), warnings  # type: ignore[arg-type]



def _cross_validate(sensors: SensorData) -> List[str]:
    """
    Перекрёстная проверка датчиков для выявления компрометированных показаний.
    """
    anomalies: List[str] = []

    time = sensors["time"]
    solar = sensors["solar_avail"]

    if solar and not _is_daytime(time):
        anomalies.append(
            f"Аномалия: солнечная генерация доступна ночью (time={time}). "
            "Показание игнорируется."
        )

    total_demand = (
        sensors["hospital_demand"]
        + sensors["school_demand"]
        + sensors["houses_demand"]
        + sensors["factory_demand"]
    )
    if total_demand > 400:
        anomalies.append(
            f"Аномалия: суммарное потребление {total_demand:.0f}% > 400%. "
            "Возможна компрометация датчиков потребителей."
        )

    return anomalies



def safe_control(sensors: SensorData, *, verbose: bool = False) -> SwitchState:
    """
    Защищённый алгоритм управления при возможной компрометации датчиков.

    Отличия от control():
    1. Валидация и санитизация всех входных данных.
    2. Перекрёстная проверка для обнаружения аномалий.
    3. Недоверенные показания заменяются консервативными значениями.
    4. Поверх результата накладываются жёсткие инварианты безопасности.

    Параметры:
      sensors — словарь с показаниями датчиков (может содержать ложные данные).
      verbose — печатать предупреждения и аномалии в stdout.

    Возвращает:
      Словарь состояний ключей (см. SwitchState), гарантирующий выполнение
      целей безопасности даже при компрометированных данных.
    """
    clean_sensors, warnings = _sanitize_sensors(sensors)
    anomalies = _cross_validate(clean_sensors)

    if verbose:
        for warning in warnings:
            print(f"[WARN] {warning}")
        for anomaly in anomalies:
            print(f"[SECURITY] {anomaly}")

    time = clean_sensors["time"]
    solar_safe = clean_sensors["solar_avail"] and _is_daytime(time)

    safe_sensors: SensorData = {
        "time": time,
        "solar_avail": solar_safe,
        "wind_strength": clean_sensors["wind_strength"],
        "battery_level": clean_sensors["battery_level"],
        "hospital_demand": clean_sensors["hospital_demand"],
        "school_demand": clean_sensors["school_demand"],
        "houses_demand": clean_sensors["houses_demand"],
        "factory_demand": clean_sensors["factory_demand"],
    }

    result = control(safe_sensors)
    result["hospital"] = True
    result["ges"] = False

    return result


# ---------------------------------------------------------------------------
# Демонстрация работы (8 ситуаций из таблицы отчёта)
# ---------------------------------------------------------------------------

TEST_CASES = [
    (
        "Сит1: день, солнце+средний ветер, батарея 85%",
        SensorData(
            time=12,
            solar_avail=True,
            wind_strength=80,
            battery_level=85,
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=80,
        ),
    ),
    (
        "Сит2: день, солнце+слабый ветер, батарея 80%",
        SensorData(
            time=14,
            solar_avail=True,
            wind_strength=20,
            battery_level=80,
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=80,
        ),
    ),
    (
        "Сит3: день, нет солнца+сильный ветер, батарея 25%",
        SensorData(
            time=10,
            solar_avail=False,
            wind_strength=75,
            battery_level=25,
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=80,
        ),
    ),
    (
        "Сит4: день, нет солнца+слабый ветер, батарея 20%",
        SensorData(
            time=16,
            solar_avail=False,
            wind_strength=15,
            battery_level=20,
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=80,
        ),
    ),
    (
        "Сит5: ночь, нет солнца+средний ветер, батарея 90%",
        SensorData(
            time=2,
            solar_avail=False,
            wind_strength=85,
            battery_level=90,
            hospital_demand=100,
            school_demand=0,
            houses_demand=50,
            factory_demand=60,
        ),
    ),
    (
        "Сит6: ночь, нет солнца+слабый ветер, батарея 75%",
        SensorData(
            time=23,
            solar_avail=False,
            wind_strength=10,
            battery_level=75,
            hospital_demand=100,
            school_demand=0,
            houses_demand=50,
            factory_demand=60,
        ),
    ),
    (
        "Сит7: ночь, нет солнца+сильный ветер, батарея 15%",
        SensorData(
            time=3,
            solar_avail=False,
            wind_strength=70,
            battery_level=15,
            hospital_demand=100,
            school_demand=0,
            houses_demand=50,
            factory_demand=60,
        ),
    ),
    (
        "Сит8: ночь, нет солнца+слабый ветер, батарея 10%",
        SensorData(
            time=1,
            solar_avail=False,
            wind_strength=5,
            battery_level=10,
            hospital_demand=100,
            school_demand=0,
            houses_demand=50,
            factory_demand=60,
        ),
    ),
]

ATTACK_CASES = [
    (
        "Атака1: ложный сигнал — солнце ночью",
        SensorData(
            time=3,
            solar_avail=True,
            wind_strength=50,
            battery_level=60,
            hospital_demand=100,
            school_demand=40,
            houses_demand=60,
            factory_demand=50,
        ),
    ),
    (
        "Атака2: некорректный уровень заряда батареи (−5%)",
        SensorData(
            time=12,
            solar_avail=True,
            wind_strength=60,
            battery_level=-5,
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=50,
        ),
    ),
    (
        "Атака3: завышенное потребление больницы (999%)",
        SensorData(
            time=12,
            solar_avail=True,
            wind_strength=60,
            battery_level=70,
            hospital_demand=999,
            school_demand=60,
            houses_demand=70,
            factory_demand=50,
        ),
    ),
    (
        "Атака4: отсутствует датчик батареи",
        SensorData(
            time=12,
            solar_avail=True,
            wind_strength=60,
            battery_level=None,  # type: ignore[arg-type]
            hospital_demand=100,
            school_demand=60,
            houses_demand=70,
            factory_demand=50,
        ),
    ),
    (
        "Атака5: слишком высокое суммарное потребление",
        SensorData(
            time=12,
            solar_avail=True,
            wind_strength=60,
            battery_level=80,
            hospital_demand=100,
            school_demand=150,
            houses_demand=150,
            factory_demand=150,
        ),
    ),
]



def _print_switch(state: SwitchState) -> str:
    icons = {True: "ВКЛ", False: "ВЫКЛ"}
    parts = []
    for key, label in [
        ("ges", "ГЭС"),
        ("solar", "Солнце"),
        ("wind", "Ветер"),
        ("battery", "Батарея"),
        ("hospital", "Больница"),
        ("school", "Школа"),
        ("houses", "Дома"),
        ("factory", "Завод"),
    ]:
        parts.append(f"{label}={icons[state[key]]}")
    return " | ".join(parts)



def run_demo() -> None:
    print("=" * 80)
    print("ЗАДАЧА 1: Штатный алгоритм control(sensors)")
    print("=" * 80)
    for desc, sensors in TEST_CASES:
        result = control(sensors)
        print(f"\n{desc}")
        print(f"  → {_print_switch(result)}")

    print("\n" + "=" * 80)
    print("ЗАДАЧА 2: Защищённый алгоритм safe_control(sensors) при атаках")
    print("=" * 80)
    for desc, sensors in ATTACK_CASES:
        print(f"\n{desc}")
        result = safe_control(sensors, verbose=True)
        print(f"  → {_print_switch(result)}")


if __name__ == "__main__":
    run_demo()
