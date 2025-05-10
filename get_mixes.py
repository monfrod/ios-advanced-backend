from yandex_music import Client
from yandex_music.landing.chart_item import ChartItem
from yandex_music.track.track import Track
# LandingBlock не нужен для прямого импорта, если мы не проверяем его тип через isinstance
# from yandex_music.landing.landing_block import LandingBlock
import traceback
from typing import List, Dict, Any, Optional


# --- Модели данных для структурированного ответа (аналогично Pydantic, но для простоты словари) ---
# ChartDataDict = Dict[str, Any] # {"chart_title": str, "chart_cover_image_url": Optional[str], "track_ids": List[str]}

def get_yandex_music_client(api_token: str) -> Optional[Client]:
    """Инициализирует клиент Яндекс.Музыки."""
    try:
        client_instance = Client(api_token).init()
        # print("Клиент Яндекс.Музыки успешно инициализирован.") # Для отладки
        return client_instance
    except Exception as e:
        print(f"Ошибка инициализации клиента Яндекс.Музыки: {e}")
        return None


def get_charts_data_structured(api_token: str) -> Dict[str, Any]:
    """
    Извлекает данные о чартах с Яндекс.Музыки и возвращает их в виде структурированного словаря.
    Возвращает словарь с ключами "charts" (список данных о чартах) и "errors" (список ошибок).
    Каждый чарт содержит: chart_title, chart_cover_image_url (плейсхолдер), track_ids.
    """
    client = get_yandex_music_client(api_token)
    if not client:
        return {"charts": [], "errors": ["Клиент Яндекс.Музыки не инициализирован."]}

    # print("\n--- Запрос данных о чартах из client.landing() ---") # Для отладки

    output_charts_list: List[Dict[str, Any]] = []
    errors_list: List[str] = []

    requested_blocks = ['chart', 'personal-playlists']
    # print(f"Попытка запросить landing с блоками: {requested_blocks}") # Для отладки

    try:
        landing_data = client.landing(blocks=requested_blocks)

        if not landing_data or not landing_data.blocks:
            errors_list.append("client.landing() не вернул данные или блоки пусты для запрошенного набора.")
            return {"charts": output_charts_list, "errors": errors_list}

        # print(f"  Успешно. Всего получено {len(landing_data.blocks)} блоков.") # Для отладки

        chart_blocks_processed_count = 0
        for block_obj in landing_data.blocks:  # block_obj это LandingBlock
            block_title = getattr(block_obj, 'title', 'N/A')
            block_type = getattr(block_obj, 'type', 'N/A')

            if block_type == 'chart':
                chart_blocks_processed_count += 1
                # print(f"\n  --- Обработка Блока Чартов #{chart_blocks_processed_count}: {block_title} ---") # Для отладки

                current_chart_data: Dict[str, Any] = {
                    "chart_title": block_title,
                    "chart_cover_image_url": "Пока не реализовано извлечение",
                    # TODO: Исследовать, как получить обложку блока
                    "track_ids": []
                    # "detailed_tracks" удален из этой структуры
                }

                entities = getattr(block_obj, 'entities', [])
                if entities:
                    # print(f"    Найдено {len(entities)} элементов (треков) в этом чарте.") # Для отладки
                    for entity_idx, entity in enumerate(entities):
                        chart_item_obj = entity.data

                        if isinstance(chart_item_obj, ChartItem):
                            track_short_obj = getattr(chart_item_obj, 'track', None)

                            if isinstance(track_short_obj, Track):  # TrackShort наследуется от Track
                                track_id = getattr(track_short_obj, 'id', None)
                                if track_id:
                                    current_chart_data["track_ids"].append(str(track_id))
                                # else:
                                # Логирование ID не найденного трека удалено для упрощения
                                # print(f"      Трек #{entity_idx + 1} в чарте '{block_title}': ID не найден.") # Для отладки
                            # else:
                            # Логирование неправильного типа track_short_obj удалено
                            # print(f"      Элемент #{entity_idx + 1} в чарте '{block_title}': chart_item_obj.track не Track (тип: {type(track_short_obj).__name__}).") # Для отладки
                        # else:
                        # Логирование неправильного типа chart_item_obj удалено
                        # print(f"      Элемент #{entity_idx + 1} в чарте '{block_title}': entity.data не ChartItem (тип: {type(chart_item_obj).__name__}).") # Для отладки
                # else:
                # print(f"    В блоке чарта '{block_title}' нет элементов (треков).") # Для отладки

                output_charts_list.append(current_chart_data)

        if chart_blocks_processed_count == 0:
            errors_list.append("Не найдено блоков с типом 'chart' в запрошенном наборе.")

        return {"charts": output_charts_list, "errors": errors_list if errors_list else None}

    except Exception as e:
        # print(f"  КРИТИЧЕСКАЯ ОШИБКА при запросе или анализе client.landing(): {e}") # Для отладки
        # traceback.print_exc() # Для отладки
        errors_list.append(f"Критическая ошибка при получении данных Яндекс.Музыки: {str(e)}")
        return {"charts": [], "errors": errors_list}


# --- Пример использования ---
if __name__ == "__main__":
    print("Запуск скрипта для получения структурированных данных о чартах...")
    # ВАЖНО: Замените на ваш действительный токен Яндекс.Музыки!
    test_api_token = "y0__xCu8NrtARje-AYg0Zu9hhNfQEdS_DMm_uaUVeUOhb-WPf-a_A"

    print(f"Используется тестовый токен: ...{test_api_token[-6:]}")

    charts_result = get_charts_data_structured(test_api_token)

    if charts_result["errors"]:
        print("\n--- Обнаружены ошибки ---")
        for error_msg in charts_result["errors"]:
            print(f"- {error_msg}")

    if charts_result["charts"]:
        print("\n--- Полученные данные о чартах ---")
        for idx, chart_info in enumerate(charts_result["charts"]):
            print(f"\nЧарт #{idx + 1}:")
            print(f"  Название: {chart_info.get('chart_title')}")
            print(f"  Обложка чарта: {chart_info.get('chart_cover_image_url')}")
            print(f"  Количество ID треков: {len(chart_info.get('track_ids', []))}")
            print(f"  Массив ID треков: {chart_info.get('track_ids')}")  # Теперь выводим сам массив ID
            print("-" * 20)
    elif not charts_result["errors"]:
        print("\nДанные о чартах не найдены, но ошибок не было.")
