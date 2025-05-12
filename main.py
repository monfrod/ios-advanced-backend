from fastapi import FastAPI, Query
from fastapi import Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from yandex_music import Client, Playlist
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from tempfile import NamedTemporaryFile
from yandex_music.landing.chart_item import ChartItem
from yandex_music.track.track import Track
from typing import List, Dict, Any
from dotenv import load_dotenv
load_dotenv()
import os

app = FastAPI()

API_KEY = os.getenv("API_KEY")

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi.json"):
        return await call_next(request)

    key = request.headers.get("X-API-KEY")
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Можно указать список разрешённых доменов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Можно хранить токен в переменной окружения или захардкодить временно
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")


def get_client():
    return Client(YANDEX_TOKEN).init()


@app.get("/search")
def search_music(query: str = Query(..., description="Поисковый запрос")):
    client = get_client()
    result = client.search(query)
    return result.to_dict()

@app.get("/track/{track_id}")
def get_track(track_id: int):
    client = get_client()
    track = client.tracks([track_id])[0]
    return track.to_dict()

@app.get("/album/{album_id}")
def get_album(album_id: int):
    client = get_client()
    album = client.albums_with_tracks(album_id)
    return album.to_dict()

@app.get("/download/{track_id}")
def download_track(track_id: int):
    client = get_client()
    track = client.tracks([track_id])[0]
    filename = f"track_{track_id}.mp3"
    track.download(filename)
    return FileResponse(path=filename, filename=filename, media_type='audio/mpeg')

@app.get("/stream/{track_id}")
def stream_track(track_id: int):
    client = get_client()
    track = client.tracks([track_id])[0]

    temp_file = NamedTemporaryFile(delete=False, suffix=".mp3")
    track.download(temp_file.name)
    temp_file.seek(0)

    return StreamingResponse(temp_file, media_type="audio/mpeg")

@app.get("/mixes")
def get_user_mixes_final():
    client = get_client()
    mixes_output = []
    try:
        # print("Запрос блоков с главной страницы (landing)...")
        landing = client.landing(blocks=['personal-playlists'])

        if not landing or not landing.blocks:
            print("Не найдены блоки на главной странице или объект landing пуст.")
            return []

        for block_idx, block in enumerate(landing.blocks):
            if block.type == 'personal-playlists':
                if not block.entities:
                    continue

                for entity_idx, entity in enumerate(block.entities):
                    if len(mixes_output) >= 4:
                        break

                    wrapper_data = entity.data  # Это GeneratedPlaylist

                    if not hasattr(wrapper_data, 'data') or not wrapper_data.data:
                        print(
                            f"    Пропуск сущности {entity_idx + 1}: отсутствует вложенный атрибут 'data' у {type(wrapper_data).__name__}.")
                        continue

                    playlist_data_source = wrapper_data.data  # Это может быть dict или объект Playlist

                    title = 'Название неизвестно'
                    playlist_uid_internal = None
                    playlist_kind = None
                    owner_uid = None
                    cover_url = None
                    track_count_from_source = 0

                    # print(f"    DEBUG: Тип playlist_data_source ({getattr(wrapper_data,'type','N/A')}): {type(playlist_data_source).__name__}")

                    if isinstance(playlist_data_source, dict):
                        # print("      DEBUG: playlist_data_source - это СЛОВАРЬ.")
                        title = playlist_data_source.get('title', 'Название неизвестно')
                        playlist_uid_internal = playlist_data_source.get('uid')
                        playlist_kind = playlist_data_source.get('kind')
                        owner_info = playlist_data_source.get('owner', {})
                        owner_uid = owner_info.get('uid') if isinstance(owner_info,
                                                                        dict) else None  # Доп. проверка для owner_info
                        cover_info = playlist_data_source.get('cover', {})
                        cover_uri_template = cover_info.get('uri') if isinstance(cover_info, dict) else None
                        track_count_from_source = playlist_data_source.get('track_count', 0)
                        if cover_uri_template:
                            cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                    elif isinstance(playlist_data_source,
                                    Playlist):  # Проверяем, не является ли это уже объектом Playlist
                        # print("      DEBUG: playlist_data_source - это ОБЪЕКТ Playlist.")
                        title = getattr(playlist_data_source, 'title', 'Название неизвестно')
                        playlist_uid_internal = getattr(playlist_data_source, 'uid', None)
                        playlist_kind = getattr(playlist_data_source, 'kind', None)
                        if hasattr(playlist_data_source, 'owner') and playlist_data_source.owner:
                            owner_uid = getattr(playlist_data_source.owner, 'uid', None)

                        if hasattr(playlist_data_source, 'cover') and playlist_data_source.cover:
                            cover_uri_template = getattr(playlist_data_source.cover, 'uri', None)
                            if cover_uri_template:
                                cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                        track_count_from_source = getattr(playlist_data_source, 'track_count', 0)
                    else:
                        print(
                            f"    Пропуск сущности: playlist_data_source имеет неожиданный тип {type(playlist_data_source).__name__} для wrapper_data.type = {getattr(wrapper_data, 'type', 'N/A')}")
                        continue

                    track_ids = []
                    # Если у нас уже есть объект Playlist из playlist_data_source, можно было бы использовать его напрямую.
                    # Но для единообразия пока оставим логику с client.users_playlists, если есть owner_uid и kind.
                    # Если playlist_data_source был Playlist, то owner_uid и kind мы из него извлекли.
                    if owner_uid is not None and playlist_kind is not None:
                        try:
                            # print(f"      Запрос полного плейлиста для OwnerUID: {owner_uid}, Kind: {playlist_kind}")
                            full_playlist_obj = client.users_playlists(user_id=owner_uid, kind=playlist_kind)

                            if full_playlist_obj:  # full_playlist_obj должен быть объектом Playlist
                                if hasattr(full_playlist_obj, 'tracks') and full_playlist_obj.tracks:
                                    for t_short in full_playlist_obj.tracks:
                                        for t_short in full_playlist_obj.tracks:
                                            if t_short and hasattr(t_short, 'id'):
                                                track = client.tracks([t_short.id])[0]
                                                track_ids.append(track.to_dict())

                                if not track_ids and hasattr(full_playlist_obj, 'fetch_tracks'):
                                    fetched_tracks_list = full_playlist_obj.fetch_tracks()
                                    if fetched_tracks_list:
                                        for t_full in fetched_tracks_list:
                                            track = client.tracks([t_full])[0]
                                            track_ids.append(track.to_dict())
                            # else:
                            # print(f"      client.users_playlists не вернул объект для OwnerUID: {owner_uid}, Kind: {playlist_kind}")
                        except Exception as e_fetch:
                            print(
                                f"    Ошибка при получении треков для плейлиста '{title}' (OwnerUID: {owner_uid}, Kind: {playlist_kind}): {e_fetch}")
                    # else:
                    # print(f"    Недостаточно данных (OwnerUID или Kind) для запроса треков плейлиста '{title}'.")

                    mixes_output.append({
                        'title': title,
                        'cover_image_url': cover_url,
                        'tracks': track_ids,
                        'track_count_from_data': track_count_from_source,
                        'fetched_track_count': len(track_ids),
                    })
            if len(mixes_output) >= 4:
                break

        return mixes_output

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА в get_user_mixes_final: {e}")
        # Для отладки можно добавить вывод трассировки:
        # import traceback
        # traceback.print_exc()
        return []

@app.get("/chart")
def get_charts_data_structured() -> Dict[str, Any]:
    """
    Извлекает данные о чартах с Яндекс.Музыки и возвращает их в виде структурированного словаря.
    Возвращает словарь с ключами "charts" (список данных о чартах) и "errors" (список ошибок).
    Каждый чарт содержит: chart_title, chart_cover_image_url (плейсхолдер), track_ids.
    """
    client = get_client()

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