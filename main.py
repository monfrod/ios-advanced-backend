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
    client = get_client()  # Ваша функция для получения клиента API
    mixes_output = []
    try:
        landing = client.landing(blocks=['personal-playlists'])

        if not landing or not landing.blocks:
            print("Блок 'personal-playlists' не найден на главной странице.")
            return []

        processed_playlists_count = 0
        for block_idx, block in enumerate(landing.blocks):
            if block.type == 'personal-playlists':
                processed_playlists_count += 1
                if not block.entities:
                    continue

                for entity_idx, entity in enumerate(block.entities):
                    if len(mixes_output) >= 4:
                        break

                    wrapper_data = entity.data
                    if not hasattr(wrapper_data, 'data') or not wrapper_data.data:
                        continue

                    playlist_data_source = wrapper_data.data

                    title = 'Название неизвестно'
                    owner_uid = None
                    playlist_kind = None
                    cover_url = None
                    track_count_from_source = 0

                    # Определение деталей плейлиста (обложка, название и т.д.)
                    if isinstance(playlist_data_source, dict):
                        title = playlist_data_source.get('title', 'Название неизвестно')
                        playlist_kind = playlist_data_source.get('kind')
                        owner_info = playlist_data_source.get('owner', {})
                        owner_uid = owner_info.get('uid') if isinstance(owner_info, dict) else None
                        cover_info = playlist_data_source.get('cover', {})
                        cover_uri_template = cover_info.get('uri') if isinstance(cover_info, dict) else None
                        if cover_uri_template:
                            cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                        track_count_from_source = playlist_data_source.get('track_count', 0)
                    elif isinstance(playlist_data_source, Playlist):  # Замените Playlist на ваш реальный класс
                        title = getattr(playlist_data_source, 'title', 'Название неизвестно')
                        playlist_kind = getattr(playlist_data_source, 'kind', None)
                        if hasattr(playlist_data_source, 'owner') and playlist_data_source.owner:
                            owner_uid = getattr(playlist_data_source.owner, 'uid', None)
                        if hasattr(playlist_data_source, 'cover') and playlist_data_source.cover:
                            cover_uri_template = getattr(playlist_data_source.cover, 'uri', None)
                            if cover_uri_template:
                                cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                        track_count_from_source = getattr(playlist_data_source, 'track_count', 0)
                    else:
                        continue

                    detailed_tracks_list: List[Dict[str, Any]] = []

                    if owner_uid is not None and playlist_kind is not None:
                        try:
                            full_playlist_obj = client.users_playlists(user_id=owner_uid, kind=playlist_kind)
                            if full_playlist_obj:
                                track_objects_from_playlist = []  # Это будут объекты-обертки или сами треки

                                # Логика получения списка треков из плейлиста
                                if hasattr(full_playlist_obj, 'fetch_tracks') and callable(
                                        getattr(full_playlist_obj, 'fetch_tracks')):
                                    fetched_tracks = full_playlist_obj.fetch_tracks()
                                    if fetched_tracks:
                                        track_objects_from_playlist.extend(fetched_tracks)
                                elif hasattr(full_playlist_obj, 'tracks') and full_playlist_obj.tracks:
                                    # Если tracks - это короткие объекты, возможно, их нужно дозагрузить
                                    # или они уже содержат .track с полной информацией
                                    track_ids_to_fetch = [
                                        str(t_short.id) for t_short in full_playlist_obj.tracks
                                        if t_short and hasattr(t_short, 'id') and t_short.id is not None
                                    ]
                                    if track_ids_to_fetch:
                                        # client.tracks() должен возвращать объекты,
                                        # которые либо сами являются полными треками,
                                        # либо содержат атрибут .track с полным треком.
                                        full_track_objects = client.tracks(track_ids_to_fetch)
                                        track_objects_from_playlist.extend(full_track_objects)

                                # Обработка каждого трека для извлечения деталей и обложки
                                for track_obj_wrapper in track_objects_from_playlist:
                                    if not track_obj_wrapper:
                                        continue

                                    actual_track = None
                                    # Предполагаем, что track_obj_wrapper может быть оберткой,
                                    # а сам трек находится в атрибуте .track
                                    if hasattr(track_obj_wrapper, 'track') and track_obj_wrapper.track:
                                        actual_track = track_obj_wrapper.track
                                    else:
                                        # Если атрибута .track нет, возможно, track_obj_wrapper - это уже сам трек
                                        # Это зависит от того, что возвращают full_playlist_obj.fetch_tracks()
                                        # и client.tracks()
                                        actual_track = track_obj_wrapper
                                        # print(f"    Предупреждение: у объекта track_obj_wrapper (ID: {getattr(track_obj_wrapper, 'id', 'N/A')}) не имеет атрибута 'track'. Обрабатывается как сам трек.")

                                    if not actual_track:
                                        print(
                                            f"    Не удалось получить объект actual_track из track_obj_wrapper (ID: {getattr(track_obj_wrapper, 'id', 'N/A')})")
                                        continue

                                    track_dict = {}
                                    # Пытаемся получить базовый словарь из actual_track
                                    if hasattr(actual_track, 'to_dict') and callable(getattr(actual_track, 'to_dict')):
                                        track_dict = actual_track.to_dict()
                                    else:
                                        # Если to_dict нет, формируем вручную (пример)
                                        track_dict['id'] = getattr(actual_track, 'id', None)
                                        track_dict['title'] = getattr(actual_track, 'title', 'Название неизвестно')
                                        # Добавьте сюда другие необходимые поля: artists, duration_ms и т.д.
                                        # Убедитесь, что actual_track имеет эти атрибуты
                                        # Например:
                                        # if hasattr(actual_track, 'artists') and actual_track.artists:
                                        #    track_dict['artists'] = [artist.name for artist in actual_track.artists if hasattr(artist, 'name')]
                                        # elif hasattr(actual_track, 'artists_name') and callable(actual_track.artists_name):
                                        #    track_dict['artists'] = actual_track.artists_name()

                                    # Получение URL обложки трека
                                    image_url = None
                                    if hasattr(actual_track, 'ima') and \
                                            hasattr(actual_track.ima, 'get_og_image_url') and \
                                            callable(getattr(actual_track.ima, 'get_og_image_url')):
                                        try:
                                            # Укажите желаемый размер, например '100x100'
                                            image_url = actual_track.ima.get_og_image_url(size='100x100')
                                        except Exception as img_err:
                                            print(
                                                f"        Ошибка при вызове get_og_image_url для трека {track_dict.get('id', 'ID неизвестен')}: {img_err}")
                                    else:
                                        # Эта ветка может сработать, если структура actual_track не такая, как ожидалось
                                        print(
                                            f"        Предупреждение: не найден метод get_og_image_url или атрибут ima у трека {track_dict.get('id', 'ID неизвестен')}")
                                        # print(f"        Атрибуты actual_track: {dir(actual_track)}")
                                        # if hasattr(actual_track, 'ima'):
                                        #    print(f"        Атрибуты actual_track.ima: {dir(actual_track.ima)}")

                                    track_dict['image_url'] = image_url  # Добавляем URL, даже если он None
                                    detailed_tracks_list.append(track_dict)

                        except Exception as e_fetch:
                            print(
                                f"    Ошибка при получении треков для плейлиста '{title}' (OwnerUID: {owner_uid}, Kind: {playlist_kind}): {e_fetch}")

                    mixes_output.append({
                        'title': title,
                        'cover_image_url': cover_url,
                        'tracks': detailed_tracks_list,  # Теперь здесь должен быть список треков с image_url
                        'track_count_from_data': track_count_from_source,
                        'fetched_track_count': len(detailed_tracks_list),
                    })
            if len(mixes_output) >= 4:
                break

        if processed_playlists_count == 0:
            print("Не найдено блоков 'personal-playlists' или они пусты.")

        return mixes_output

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА в get_user_mixes_final: {e}")
        # import traceback # Для детальной отладки можно раскомментировать
        # traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


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