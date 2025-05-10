from yandex_music import Client

print("я работаю")
client = Client('y0__xCu8NrtARje-AYg0Zu9hhNfQEdS_DMm_uaUVeUOhb-WPf-a_A').init()
liked_tracks = client.users_likes_tracks()
first_track = liked_tracks.tracks[2].fetch_track()
first_track.download("pp3.mp3")
print("я работаю")