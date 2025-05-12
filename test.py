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
    token = "y0__xCu8NrtARje-AYg0Zu9hhNfQEdS_DMm_uaUVeUOhb-WPf-a_A"
    if not token:
        raise RuntimeError("YANDEX_TOKEN не найден в переменных окружения.")
    return Client(token).init()

# --- Pydantic модели для структурированного ответа ---
def get_user_mixes_final():
    client = get_client()
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
                    elif isinstance(playlist_data_source, Playlist):
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
                                track_objects_from_playlist = []
                                if hasattr(full_playlist_obj, 'fetch_tracks') and callable(
                                        getattr(full_playlist_obj, 'fetch_tracks')):
                                    fetched_tracks = full_playlist_obj.fetch_tracks()
                                    if fetched_tracks:
                                        track_objects_from_playlist.extend(fetched_tracks)
                                elif hasattr(full_playlist_obj, 'tracks') and full_playlist_obj.tracks:
                                    track_ids_to_fetch = [
                                        str(t_short.id) for t_short in full_playlist_obj.tracks
                                        if t_short and hasattr(t_short, 'id') and t_short.id is not None
                                    ]
                                    if track_ids_to_fetch:
                                        full_track_objects = client.tracks(track_ids_to_fetch)
                                        track_objects_from_playlist.extend(full_track_objects)

                                for track_obj in track_objects_from_playlist:
                                    if track_obj:
                                        print(dir(track_obj.track.get_cover_url(size='50x50')))
                                        track_dict = track_obj.to_dict()
                                        track_dict["image_url"] = track_obj.track.get_og_image_url()
                                        detailed_tracks_list.append(track_dict)
                        except Exception as e_fetch:
                            print(
                                f"    Ошибка при получении треков для плейлиста '{title}' (OwnerUID: {owner_uid}, Kind: {playlist_kind}): {e_fetch}")

                    mixes_output.append({
                        'title': title,
                        'cover_image_url': cover_url,
                        'tracks': detailed_tracks_list,
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
        # traceback.print_exc() # Убрано
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


if __name__ == '__main__':
    client = get_client()
    get_user_mixes_final()