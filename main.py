from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from yandex_music import Client, Playlist  # Playlist используется для isinstance
from yandex_music.track.track import Track  # Track используется для isinstance
from fastapi.responses import FileResponse, StreamingResponse
from tempfile import NamedTemporaryFile
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import os
import traceback  # Для детальной отладки ошибок на сервере

# --- Pydantic модели для структурированного ответа ---
from pydantic import BaseModel


class ArtistInfo(BaseModel):
    id: int
    name: str


class TrackInfo(BaseModel):
    id: str
    title: str
    artists: List[ArtistInfo]
    cover_url: Optional[str] = None
    duration_ms: Optional[int] = None


class MixInfo(BaseModel):
    title: str
    cover_image_url: Optional[str] = None
    tracks: List[TrackInfo]
    # track_count_from_data: int # Можно убрать, если len(tracks) достаточно
    # fetched_track_count: int # Можно убрать, если len(tracks) достаточно


# --- Загрузка переменных окружения ---
load_dotenv()

app = FastAPI(
    title="Yandex Music API Proxy",
    description="Прокси-сервер для некоторых эндпоинтов Яндекс.Музыки",
    version="1.0.1"
)

# --- Получение ключей из переменных окружения ---
BACKEND_API_KEY = os.getenv("API_KEY")  # Ключ для доступа к этому бэкенду
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")  # Токен для Яндекс.Музыки

if not BACKEND_API_KEY:
    print("ПРЕДУПРЕЖДЕНИЕ: Переменная окружения API_KEY не установлена. Защита эндпоинтов не будет работать.")
if not YANDEX_TOKEN:
    print(
        "КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения YANDEX_TOKEN не установлена. Сервер не сможет обращаться к Яндекс.Музыке.")
    # В реальном приложении здесь можно было бы остановить запуск сервера, если токен критичен
    # exit(1)


# --- Middleware для проверки API ключа ---
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Пропускаем проверку для документации Swagger/OpenAPI
    if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi.json"):
        return await call_next(request)

    if not BACKEND_API_KEY:  # Если API_KEY на сервере не задан, пропускаем проверку (небезопасно)
        # print("Проверка API ключа пропущена, так как API_KEY не установлен на сервере.")
        return await call_next(request)

    key_from_header = request.headers.get("X-API-KEY")
    if key_from_header != BACKEND_API_KEY:
        print(f"Доступ запрещен: Неверный X-API-KEY. Получен: {key_from_header}")
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")

    return await call_next(request)


# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательная функция для инициализации клиента Яндекс.Музыки ---
_client_instance = None  # Кэшируем инстанс клиента


def get_client() -> Client:
    global _client_instance
    if _client_instance is None:
        if not YANDEX_TOKEN:
            # Эта проверка уже есть выше, но дублируем на случай прямого вызова
            raise HTTPException(status_code=500, detail="Токен Яндекс.Музыки не сконфигурирован на сервере.")
        try:
            _client_instance = Client(YANDEX_TOKEN).init()
            print("Клиент Яндекс.Музыки успешно инициализирован.")
        except Exception as e:
            print(f"Критическая ошибка инициализации клиента Яндекс.Музыки: {e}")
            raise HTTPException(status_code=503, detail=f"Ошибка инициализации клиента Яндекс.Музыки: {e}")
    return _client_instance


# --- Эндпоинты ---

@app.get("/search", summary="Поиск музыки")
def search_music(query: str = Query(..., description="Поисковый запрос")):
    client = get_client()
    try:
        search_result = client.search(query)
        if search_result:
            return search_result.to_dict()  # Объекты yandex-music часто имеют to_dict()
        return {}
    except Exception as e:
        print(f"Ошибка при поиске '{query}': {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при выполнении поиска: {e}")


@app.get("/track/{track_id}", summary="Получить информацию о треке")
def get_track(track_id: str):  # ID трека может быть строкой (например, "12345:678")
    client = get_client()
    try:
        # client.tracks ожидает список ID
        tracks = client.tracks([track_id])
        if tracks and tracks[0]:
            return tracks[0].to_dict()
        raise HTTPException(status_code=404, detail="Трек не найден")
    except Exception as e:
        print(f"Ошибка при получении трека {track_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при получении информации о треке: {e}")


@app.get("/album/{album_id}", summary="Получить информацию об альбоме с треками")
def get_album(album_id: int):
    client = get_client()
    try:
        album = client.albums_with_tracks(album_id)
        if album:
            return album.to_dict()
        raise HTTPException(status_code=404, detail="Альбом не найден")
    except Exception as e:
        print(f"Ошибка при получении альбома {album_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при получении информации об альбоме: {e}")


@app.get("/download/{track_id}", summary="Скачать трек (сохраняет на сервере)")
def download_track(track_id: str):
    client = get_client()
    try:
        tracks = client.tracks([track_id])
        if not (tracks and tracks[0]):
            raise HTTPException(status_code=404, detail="Трек не найден для скачивания")

        track = tracks[0]
        # Используем более безопасное имя файла
        safe_title = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in track.title)
        safe_artists = "".join(
            c if c.isalnum() or c in (' ', '_', '-') else '_' for c in track.artists_name()[0] if track.artists_name())

        filename_base = f"{safe_artists} - {safe_title}".strip(" _-")
        if not filename_base:  # Если название и артист пустые или состоят только из спецсимволов
            filename_base = f"track_{track_id}"
        filename = f"{filename_base}.mp3"

        # Создаем временную директорию для скачивания, если нужно
        # download_dir = "downloaded_tracks"
        # os.makedirs(download_dir, exist_ok=True)
        # filepath = os.path.join(download_dir, filename)

        # Скачивание во временный файл, чтобы избежать проблем с именами и путями
        with NamedTemporaryFile(delete=False, suffix=".mp3") as tmpfile:
            track.download(tmpfile.name, bitrate_in_kbps=192)  # Укажите желаемый битрейт
            filepath_to_serve = tmpfile.name

        # Важно: FileResponse удалит временный файл после отправки, если он был создан с delete=True
        # Если delete=False, нужно будет управлять удалением файла самостоятельно
        # Для простоты, можно не удалять сразу, но в продакшене это нужно продумать
        return FileResponse(path=filepath_to_serve, filename=filename, media_type='audio/mpeg')
        # После отправки файла, его можно удалить, если он временный
        # finally:
        #    if os.path.exists(filepath_to_serve):
        #        os.remove(filepath_to_serve)

    except Exception as e:
        print(f"Ошибка при скачивании трека {track_id}: {e}")
        # traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Ошибка при скачивании трека: {e}")


@app.get("/stream/{track_id}", summary="Стриминг трека")
def stream_track(track_id: str):
    client = get_client()
    try:
        tracks = client.tracks([track_id])
        if not (tracks and tracks[0]):
            raise HTTPException(status_code=404, detail="Трек не найден для стриминга")
        track = tracks[0]

        # Создаем временный файл для скачивания
        temp_file = NamedTemporaryFile(delete=False, suffix=".mp3")
        track.download(temp_file.name, bitrate_in_kbps=192)  # Скачиваем трек
        temp_file.close()  # Закрываем файл, чтобы StreamingResponse мог его прочитать

        # Создаем генератор для стриминга файла
        def file_iterator(file_path: str, chunk_size: int = 8192):
            try:
                with open(file_path, "rb") as f:
                    while chunk := f.read(chunk_size):
                        yield chunk
            finally:
                os.remove(file_path)  # Удаляем временный файл после стриминга

        return StreamingResponse(file_iterator(temp_file.name), media_type="audio/mpeg")

    except Exception as e:
        print(f"Ошибка при стриминге трека {track_id}: {e}")
        # traceback.print_exc()
        if 'temp_file' in locals() and temp_file.name and os.path.exists(temp_file.name):
            os.remove(temp_file.name)  # Убедимся, что временный файл удален в случае ошибки
        raise HTTPException(status_code=500, detail=f"Ошибка при стриминге трека: {e}")


@app.get("/mixes", response_model=List[MixInfo],
         summary="Получить персональные миксы пользователя с детальной информацией о треках")
def get_user_detailed_mixes() -> List[MixInfo]:
    client = get_client()
    mixes_output: List[MixInfo] = []

    try:
        landing = client.landing(blocks=['personal-playlists'])
        if not landing or not landing.blocks:
            print("Блок 'personal-playlists' не найден на главной странице.")
            return []

        for block in landing.blocks:
            if block.type == 'personal-playlists':
                if not block.entities:
                    continue

                for entity in block.entities:
                    if len(mixes_output) >= 4:  # Ограничение на 4 микса
                        break

                    wrapper_data = entity.data
                    if not hasattr(wrapper_data, 'data') or not wrapper_data.data:
                        continue

                    playlist_data_source = wrapper_data.data

                    playlist_title = 'Название неизвестно'
                    owner_uid = None
                    playlist_kind = None
                    playlist_cover_url = None

                    if isinstance(playlist_data_source, dict):
                        playlist_title = playlist_data_source.get('title', 'Название неизвестно')
                        playlist_kind = playlist_data_source.get('kind')
                        owner_info = playlist_data_source.get('owner', {})
                        owner_uid = owner_info.get('uid') if isinstance(owner_info, dict) else None
                        cover_info = playlist_data_source.get('cover', {})
                        cover_uri_template = cover_info.get('uri') if isinstance(cover_info, dict) else None
                        if cover_uri_template:
                            playlist_cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                    elif isinstance(playlist_data_source, Playlist):
                        playlist_title = getattr(playlist_data_source, 'title', 'Название неизвестно')
                        playlist_kind = getattr(playlist_data_source, 'kind', None)
                        if hasattr(playlist_data_source, 'owner') and playlist_data_source.owner:
                            owner_uid = getattr(playlist_data_source.owner, 'uid', None)
                        if hasattr(playlist_data_source, 'cover') and playlist_data_source.cover:
                            cover_uri_template = getattr(playlist_data_source.cover, 'uri', None)
                            if cover_uri_template:
                                playlist_cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                    else:
                        continue  # Пропускаем, если тип данных неожиданный

                    tracks_details_list: List[TrackInfo] = []
                    if owner_uid is not None and playlist_kind is not None:
                        try:
                            full_playlist_obj = client.users_playlists(user_id=owner_uid, kind=playlist_kind)
                            if full_playlist_obj:
                                track_objects_to_process = []
                                if hasattr(full_playlist_obj, 'tracks') and full_playlist_obj.tracks:
                                    track_objects_to_process.extend(full_playlist_obj.tracks)

                                if not track_objects_to_process and hasattr(full_playlist_obj, 'fetch_tracks'):
                                    fetched_tracks = full_playlist_obj.fetch_tracks()
                                    if fetched_tracks:
                                        track_objects_to_process.extend(fetched_tracks)

                                for track_obj in track_objects_to_process:
                                    if not track_obj or not (hasattr(track_obj, 'id') and track_obj.id is not None):
                                        continue

                                    track_id_str = str(track_obj.id)
                                    track_title_str = getattr(track_obj, 'title', 'N/A')
                                    duration_ms_val = getattr(track_obj, 'duration_ms', None)

                                    artists_info_list: List[ArtistInfo] = []
                                    if hasattr(track_obj, 'artists') and track_obj.artists:
                                        for art_obj in track_obj.artists:
                                            if hasattr(art_obj, 'id') and art_obj.id is not None and \
                                                    hasattr(art_obj, 'name') and art_obj.name is not None:
                                                artists_info_list.append(ArtistInfo(id=art_obj.id, name=art_obj.name))

                                    track_cover_url_val = None
                                    if hasattr(track_obj, 'albums') and track_obj.albums and len(track_obj.albums) > 0:
                                        album = track_obj.albums[0]
                                        if hasattr(album, 'cover_uri') and album.cover_uri:
                                            track_cover_url_val = f"https://{album.cover_uri.replace('%%', '50x50')}"
                                    elif hasattr(track_obj, 'cover_uri') and track_obj.cover_uri:
                                        track_cover_url_val = f"https://{track_obj.cover_uri.replace('%%', '50x50')}"

                                    tracks_details_list.append(TrackInfo(
                                        id=track_id_str,
                                        title=track_title_str,
                                        artists=artists_info_list,
                                        cover_url=track_cover_url_val,
                                        duration_ms=duration_ms_val
                                    ))
                        except Exception as e_fetch_tracks:
                            print(f"Ошибка при получении треков для микса '{playlist_title}': {e_fetch_tracks}")

                    mixes_output.append(MixInfo(
                        title=playlist_title,
                        cover_image_url=playlist_cover_url,
                        tracks=tracks_details_list
                    ))
            if len(mixes_output) >= 4:  # Прерываем внешний цикл тоже
                break

        if not mixes_output and chart_blocks_processed_count == 0 and block.type != 'personal-playlists':  # Добавил проверку на случай если personal-playlists вообще не было
            print("Не найдено блоков 'personal-playlists' или они пусты.")

        return mixes_output

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА в get_user_detailed_mixes: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера при получении миксов: {e}")


@app.get("/chart", summary="Получить информацию о чартах Яндекс.Музыки (упрощенный)")
def get_charts_data_simplified() -> Dict[str, Any]:
    """
    Извлекает данные о чартах с Яндекс.Музыки.
    Возвращает словарь с ключами "charts" (список данных о чартах) и "errors" (список ошибок).
    Каждый чарт содержит: chart_title, chart_cover_image_url (плейсхолдер), track_ids.
    """
    client = get_client()
    output_charts_list: List[Dict[str, Any]] = []
    errors_list: List[str] = []
    requested_blocks = ['chart', 'personal-playlists']

    try:
        landing_data = client.landing(blocks=requested_blocks)
        if not landing_data or not landing_data.blocks:
            errors_list.append("client.landing() не вернул данные или блоки пусты.")
            return {"charts": output_charts_list, "errors": errors_list}

        chart_blocks_processed_count = 0
        for block_obj in landing_data.blocks:
            block_title = getattr(block_obj, 'title', 'N/A')
            block_type = getattr(block_obj, 'type', 'N/A')

            if block_type == 'chart':
                chart_blocks_processed_count += 1
                current_chart_data: Dict[str, Any] = {
                    "chart_title": block_title,
                    "chart_cover_image_url": "Пока не реализовано извлечение",
                    "track_ids": []
                }
                entities = getattr(block_obj, 'entities', [])
                if entities:
                    for entity in entities:
                        chart_item_obj = entity.data
                        if isinstance(chart_item_obj, ChartItem):
                            track_short_obj = getattr(chart_item_obj, 'track', None)
                            if isinstance(track_short_obj, Track):
                                track_id = getattr(track_short_obj, 'id', None)
                                if track_id:
                                    current_chart_data["track_ids"].append(str(track_id))
                output_charts_list.append(current_chart_data)

        if chart_blocks_processed_count == 0:
            errors_list.append("Не найдено блоков с типом 'chart'.")

        return {"charts": output_charts_list, "errors": errors_list if errors_list else None}
    except Exception as e:
        errors_list.append(f"Критическая ошибка при получении данных чартов: {str(e)}")
        return {"charts": [], "errors": errors_list}

# --- Запуск сервера (если файл запускается напрямую) ---
# if __name__ == "__main__":
#     import uvicorn
#     print("Для запуска сервера используйте команду: uvicorn имя_файла:app --reload")
#     print(f"Пример: uvicorn {os.path.basename(__file__).replace('.py', '')}:app --reload")
#     print(f"Не забудьте установить YANDEX_TOKEN и API_KEY как переменные окружения.")
# uvicorn.run(app, host="0.0.0.0", port=8000) # Для примера, обычно запускается через uvicorn CLI
