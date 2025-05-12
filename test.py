from fastapi import FastAPI, Query, Request, HTTPException  # FastAPI и Query нужны для эндпоинта
from yandex_music import Client, Playlist  # Playlist используется для isinstance
from yandex_music.track.track import Track  # Track используется для isinstance
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import traceback  # Для детальной отладки ошибок на сервере
import os  # Для os.getenv, если get_client() будет здесь же

app = FastAPI()


# ПРЕДПОЛАГАЕТСЯ, ЧТО СЛЕДУЮЩИЕ КОМПОНЕНТЫ УЖЕ ОПРЕДЕЛЕНЫ В ВАШЕМ ОСНОВНОМ ФАЙЛЕ:
# 1. app = FastAPI()
# 2. Функция get_client() для инициализации yandex_music.Client
# 3. YANDEX_TOKEN и API_KEY (если используется middleware для X-API-KEY)

def get_client():
    token = os.getenv("y0__xCu8NrtARje-AYg0Zu9hhNfQEdS_DMm_uaUVeUOhb-WPf-a_A")
    if not token:
        raise RuntimeError("YANDEX_TOKEN не найден в переменных окружения.")
    return Client(token).init()

# --- Pydantic модели для структурированного ответа ---
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
    # Закомментированные поля ниже можно добавить, если они нужны в ответе
    # track_count_from_data: int
    # fetched_track_count: int


# --- Обновленный эндпоинт /mixes ---
# Убедитесь, что ваш декоратор @app.get("/mixes"...) использует правильный экземпляр app
# и что функция get_client() доступна в этом контексте.

@app.get("/mixes", response_model=List[MixInfo], summary="Получить персональные миксы пользователя с детальной информацией о треках")
def get_user_detailed_mixes() -> List[MixInfo]:
    client = get_client() # Ваша функция для получения инициализированного клиента
    mixes_output: List[MixInfo] = []

    try:
        landing = client.landing(blocks=['personal-playlists'])
        print("Загружен landing с блоками:", [block.type for block in landing.blocks])
        if not landing or not landing.blocks:
            print("Блок 'personal-playlists' не найден на главной странице.")
            # В API лучше вернуть пустой список или ошибку, а не просто печатать
            # raise HTTPException(status_code=404, detail="Блок 'personal-playlists' не найден")
            return [] # Возвращаем пустой список, если блок не найден

        processed_playlists_count = 0 # Счетчик для отслеживания обработанных плейлистов из блока
        for block in landing.blocks:
            if block.type == 'personal-playlists':
                print(f"Обрабатывается блок: {block.type}, количество сущностей: {len(block.entities) if block.entities else 0}")
                processed_playlists_count +=1
                if not block.entities:
                    continue

                for entity in block.entities:
                    if len(mixes_output) >= 4: # Ограничение на 4 микса
                        break

                    wrapper_data = entity.data
                    if not hasattr(wrapper_data, 'data') or not wrapper_data.data:
                        # print(f"Пропуск сущности: отсутствует вложенный атрибут 'data' у {type(wrapper_data).__name__}.")
                        continue

                    playlist_data_source = wrapper_data.data

                    playlist_title = 'Название неизвестно'
                    owner_uid = None
                    playlist_kind = None
                    playlist_cover_url = None
                    # track_count_from_source_api = 0 # Если нужно это поле

                    if isinstance(playlist_data_source, dict):
                        playlist_title = playlist_data_source.get('title', 'Название неизвестно')
                        playlist_kind = playlist_data_source.get('kind')
                        owner_info = playlist_data_source.get('owner', {})
                        owner_uid = owner_info.get('uid') if isinstance(owner_info, dict) else None
                        cover_info = playlist_data_source.get('cover', {})
                        cover_uri_template = cover_info.get('uri') if isinstance(cover_info, dict) else None
                        if cover_uri_template:
                            playlist_cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                        # track_count_from_source_api = playlist_data_source.get('track_count', 0)
                    elif isinstance(playlist_data_source, Playlist):
                        playlist_title = getattr(playlist_data_source, 'title', 'Название неизвестно')
                        playlist_kind = getattr(playlist_data_source, 'kind', None)
                        if hasattr(playlist_data_source, 'owner') and playlist_data_source.owner:
                            owner_uid = getattr(playlist_data_source.owner, 'uid', None)
                        if hasattr(playlist_data_source, 'cover') and playlist_data_source.cover:
                            cover_uri_template = getattr(playlist_data_source.cover, 'uri', None)
                            if cover_uri_template:
                                playlist_cover_url = f"https://{cover_uri_template.replace('%%', '200x200')}"
                        # track_count_from_source_api = getattr(playlist_data_source, 'track_count', 0)
                    else:
                        # print(f"Пропуск сущности: playlist_data_source имеет неожиданный тип {type(playlist_data_source).__name__}")
                        continue

                    print(f"Найден плейлист: '{playlist_title}', владелец: {owner_uid}, kind: {playlist_kind}")

                    tracks_details_list: List[TrackInfo] = []
                    if owner_uid is not None and playlist_kind is not None:
                        try:
                            full_playlist_obj = client.users_playlists(user_id=owner_uid, kind=playlist_kind)
                            if full_playlist_obj:
                                track_objects_to_process = []
                                # Сначала пытаемся получить треки из .tracks (обычно это TrackShort)
                                if hasattr(full_playlist_obj, 'tracks') and full_playlist_obj.tracks:
                                    track_objects_to_process.extend(full_playlist_obj.tracks)

                                # Если .tracks пуст, но есть .fetch_tracks(), используем его
                                if not track_objects_to_process and hasattr(full_playlist_obj, 'fetch_tracks') and callable(getattr(full_playlist_obj, 'fetch_tracks')):
                                    # print(f"INFO: .tracks пуст для плейлиста '{playlist_title}', вызываем fetch_tracks().")
                                    fetched_tracks = full_playlist_obj.fetch_tracks() # Возвращает List[Track]
                                    if fetched_tracks:
                                        track_objects_to_process.extend(fetched_tracks)

                                for track_obj_item in track_objects_to_process: # track_obj_item может быть TrackShort или Track
                                    if not track_obj_item or not (hasattr(track_obj_item, 'id') and track_obj_item.id is not None):
                                        continue # Пропускаем, если нет ID

                                    # Для получения полных данных, если это TrackShort, может потребоваться client.tracks([track_obj_item.id])[0]
                                    # Но часто TrackShort уже содержит достаточно информации.
                                    # Если track_obj_item это уже полный Track (после fetch_tracks), то все поля должны быть доступны.

                                    track_id_str = str(track_obj_item.id)
                                    track_title_str = getattr(track_obj_item, 'title', 'N/A')
                                    duration_ms_val = getattr(track_obj_item, 'duration_ms', None)

                                    artists_info_list: List[ArtistInfo] = []
                                    if hasattr(track_obj_item, 'artists') and track_obj_item.artists:
                                        for art_obj in track_obj_item.artists:
                                            if hasattr(art_obj, 'id') and art_obj.id is not None and \
                                               hasattr(art_obj, 'name') and art_obj.name is not None:
                                                artists_info_list.append(ArtistInfo(id=art_obj.id, name=art_obj.name))

                                    track_cover_url_val = None
                                    # Обложка трека обычно берется с его альбома
                                    if hasattr(track_obj_item, 'albums') and track_obj_item.albums and len(track_obj_item.albums) > 0:
                                        album_for_cover = track_obj_item.albums[0]
                                        if hasattr(album_for_cover, 'cover_uri') and album_for_cover.cover_uri:
                                            track_cover_url_val = f"https://{album_for_cover.cover_uri.replace('%%', '50x50')}"
                                    elif hasattr(track_obj_item, 'cover_uri') and track_obj_item.cover_uri: # Резервный вариант, если есть у самого трека
                                         track_cover_url_val = f"https://{track_obj_item.cover_uri.replace('%%', '50x50')}"

                                    tracks_details_list.append(TrackInfo(
                                        id=track_id_str,
                                        title=track_title_str,
                                        artists=artists_info_list,
                                        cover_url=track_cover_url_val,
                                        duration_ms=duration_ms_val
                                    ))
                        except Exception as e_fetch_tracks:
                            print(f"Ошибка при получении или обработке треков для микса '{playlist_title}': {e_fetch_tracks}")
                            # traceback.print_exc()

                    print(f"Плейлист '{playlist_title}' содержит {len(tracks_details_list)} треков")

                    mixes_output.append(MixInfo(
                        title=playlist_title,
                        cover_image_url=playlist_cover_url,
                        tracks=tracks_details_list
                        # track_count_from_data=track_count_from_source_api,
                        # fetched_track_count=len(tracks_details_list)
                    ))
            if len(mixes_output) >= 4: # Прерываем внешний цикл тоже, если уже собрали 4 микса
                break

        if processed_playlists_count == 0: # Если блок personal-playlists был, но пустой, или его не было
             print("Не найдено блоков 'personal-playlists' или они пусты.")
             # Можно вернуть ошибку 404, если миксы не найдены
             # raise HTTPException(status_code=404, detail="Персональные миксы не найдены.")

        print(f"Итоговое количество миксов для возврата: {len(mixes_output)}")
        return mixes_output

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА в get_user_detailed_mixes: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера при получении миксов: {str(e)}")
