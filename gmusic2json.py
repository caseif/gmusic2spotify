#!/usr/bin/python3

from getpass import getpass
import json
import traceback
from uuid import UUID, uuid4

from gmusicapi.clients import Mobileclient

class Song:
    def __init__(self, id, artist, title, album):
        self.id = id
        self.artist = artist
        self.title = title
        self.album = album
    
    def __repr__(self):
        return "<Song artist:\"%s\" title:\"%s\" album:\"%s\">" % (self.artist, self.title, self.album)

class Playlist:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.songs = []
    
    def add_song(self, song):
        self.songs.append(song)

def parse_library_to_json(user, passphrase, json_output):
    client = Mobileclient()

    print("Attempting to authenticate with Google Play Music...")

    if not client.login(user, passphrase, Mobileclient.FROM_MAC_ADDRESS):
        print("Failed to authenticate!")
        exit(-1)

    print("Successfully authenticated.")

    print("Fetching listing of songs in library...")

    api_songs = client.get_all_songs()

    # map of songs the script has ingested
    local_songs = {}

    store_to_uuid = {}

    skipped = 0

    for api_song in api_songs:
        try:
            id = UUID(api_song['id'])

            song = Song(id, api_song['artist'], api_song['title'], api_song['album'])

            local_songs[id] = song

            if 'storeId' in api_song:
                store_to_uuid[api_song['storeId']] = id
        except:
            skipped += 1
            traceback.print_exc()
            print("Failed to ingest song with ID %s" % api_song['id'])

    print("Found %d songs." % len(local_songs))
    print("Skipped %d songs." % skipped)

    print("Fetching playlist listing...")

    api_playlist_entries = client.get_all_user_playlist_contents()

    # dict of playlists the script is aware of (they have not necessarily been fully constructed yet)
    local_playlists = {}

    added = 0
    skipped = 0

    for entry in api_playlist_entries:
        try:
            playlist_id = UUID(entry['id'])

            playlist = Playlist(id, entry['name'])

            local_playlists[playlist_id] = playlist

            for track in entry['tracks']:
                try:
                    base_id = track['trackId']

                    # trackId is different depending on whether the track is from the store or user-uploaded
                    if track['source'] == '2':
                        # we need to map the store ID to the track's UUID

                        # if we aren't aware of the track already, we can create a representation from the entry data
                        if not base_id in store_to_uuid:
                            if not 'track' in track:
                                print("Failed to construct representation for song with store ID %s." % base_id)
                                skipped += 1
                                continue

                            track_info = track['track']

                            uuid = uuid4()

                            store_to_uuid[base_id] = uuid

                            song = Song(uuid, track_info['artist'], track_info['title'], track_info['album'])

                            local_songs[uuid] = song

                            playlist.add_song(song)

                        track_id = store_to_uuid[base_id]
                    else:
                        # we can just use trackId directly
                        track_id = UUID(base_id)

                    if not track_id in local_songs.keys():
                        print("Found non-existent song in playlist with ID %s." % track_id)
                        skipped += 1
                        continue

                    song = local_songs[track_id]

                    playlist.add_song(song)

                    added += 1
                except:
                    skipped += 1
                    traceback.print_exc()
                    print("Failed to process playlist track with ID %s." % track['trackId'])
        except:
            traceback.print_exc()
            print("Failed to process playlist with ID %s." % entry['id'])

    print("Found %d entries in %d playlists." % (added, len(local_playlists)))
    print("Skipped %d entries." % skipped)

    print("Serializing library data to JSON...")

    songsDict = {}

    # serialize songs to map
    for song in local_songs.values():
        songsDict[str(song.id)] = {
            'artist': song.artist,
            'title': song.title,
            'album': song.album,
        }
    
    playlistList = []

    # serialize playlists as unlabeled list
    for playlist in local_playlists.values():
        songs = []
        for song in playlist.songs:
            songs.append(str(song.id))
        playlistList.append({
            'name': playlist.name,
            'songs': songs,
        })
    
    # create complete serial of library
    serial = {
        'songs': songsDict,
        'playlists': playlistList,
    }

    print("Writing JSON to disk...")

    json.dump(serial, json_output, indent=4)

    print("Done!")

if __name__ == "__main__":
    print("Google username: ", end='')
    user = input()

    passphrase = getpass("Google passphrase (or app-specific password for 2FA users): ")

    with open('output_library.json', 'w+') as json_file:
        parse_library_to_json(user, passphrase, json_file)
