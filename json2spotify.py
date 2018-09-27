#!/usr/bin/python3

from datetime import datetime, time, timedelta
from getpass import getpass
import json
import re
from sys import stdout
from uuid import UUID

import spotipy
from spotipy.util import prompt_for_user_token

from spotify_auth import authenticate

class Song:
    def __init__(self, artist, title, album):
        self.artist = artist
        self.title = title
        self.album = album
        self.playlists = []
    
    def add_playlist(self, playlist):
        self.playlists.append(playlist)

    def __repr__(self):
        return "<Song artist:\"%s\" title:\"%s\" album:\"%s\">" % (self.artist, self.title, self.album)

class Playlist:
    def __init__(self, name):
        self.name = name
        self.songs = []
    
    def add_song(self, song):
        self.songs.append(song)

def progress_bar(value, endvalue, eta=-1, bar_length=20):
    percent = float(value) / endvalue
    eta_str = (datetime.min + timedelta(seconds=eta)).time().strftime('%H:%M:%S') if eta != -1 else '???'
    filled = '\u2588' * int(round(percent * bar_length))
    empty = '\u2591' * (bar_length - len(filled))

    stdout.write("\r(%d/%d) %s %s%% (ETA: %s)" % (value, endvalue, filled + empty, int(round(percent * 100)), eta_str))
    stdout.flush()

def shift(l, v):
    l.pop(0)
    l.append(v)

# apostrophes should be removed entirely (instead of replaced by spaces)
APOS_REGEX = re.compile('\'')
# most non-alphanumeric characters cause problems, and they don't provide any disambiguation
NON_AN_REGEX = re.compile('[^A-Za-zÀ-ÿ0-9-_ ]')
# a mismatch in the leading "the" in track/artist names is a common point of failure
THE_REGEX = re.compile('^The ')

def sanitize_field(v):
    return re.sub(THE_REGEX, '', re.sub(NON_AN_REGEX, ' ', re.sub(APOS_REGEX, '', v)))

# all of the following regexes are usually used to separate multiple artists
# it's usually "good enough" to only search for the first artist -
#     it usually only fails when a featured artist or remixer isn't properly credited as an artist
COMMA_REGEX = re.compile(', (.*)')
AMP_REGEX = re.compile(' & (.*)')
X_REGEX = re.compile(' x (.*)')
VS_REGEX = re.compile(' vs\.? (.*)')

def sanitize_artist(v):
    return sanitize_field(re.sub(VS_REGEX, '', re.sub(X_REGEX, '', re.sub(AMP_REGEX, '', re.sub(COMMA_REGEX, '', v)))))

# a mismatch in whether the featured artist is credited in the track name is a common point of failure
FEAT_REGEX = re.compile(' [\(\[][Ff](ea)?t\.? (.*)[\)\]]')

def sanitize_title(v):
    return sanitize_field(re.sub(FEAT_REGEX, '', v))

def import_library_from_json(username, client_id, client_secret, json_input):
    library_mod_token = authenticate(username, client_id, client_secret, 'user-library-modify')

    print("Creating Spotify API instance...")

    spotify = spotipy.Spotify(auth=library_mod_token)

    print("Loading library JSON...")

    library_json = json.load(json_input)

    song_list = library_json['songs']

    songs = {}

    print("Ingesting song list...")

    for uuid, serial in song_list.items():
        songs[UUID(uuid)] = Song(serial['artist'], serial['title'], serial['album'])

    print("Successfully imported %d songs." % len(songs))

    print("Ingesting playlist list...")

    playlist_list = library_json['playlists']

    playlists = []

    for serial in playlist_list:
        playlist = Playlist(serial['name'])
        playlists.append(playlist)
        for song in serial['songs']:
            playlist.add_song(songs[UUID(song)])
            songs[UUID(song)].add_playlist(playlist)

    print("Successfully imported %d playlists." % len(playlists))

    spotify_ids = {}

    found = 0
    failed = 0

    failed_songs = []

    print("Matching songs on Spotify...")

    MAX_SPEEDS = 50

    speeds = []
    last_search = None
    last_speed_update = None
    i = 0

    eta = 0
    for local_id, song in songs.items():
        #break

        i += 1

        if last_search != None:
            cur_speed = 1 / (datetime.now() - last_search).total_seconds()

            if len(speeds) < MAX_SPEEDS:
                speeds.append(cur_speed)
            else:
                shift(speeds, cur_speed)

            avg_speed = sum(speeds) / len(speeds)

            if last_speed_update == None or (datetime.now() - last_speed_update).total_seconds() >= 1:
                eta = int(float(len(songs) - i) / avg_speed) if avg_speed > 0 else -1
                last_speed_update = datetime.now()
            
        last_search = datetime.now()

        progress_bar(i, len(songs), eta)

        artist = song.artist
        title = song.title

        # We have three different levels of heuristics which we use to match tracks:
        #   1) Pass the artist and title as-is, and hope Spotify turns something up.
        #   2) Transform the artist and title, then pass them on to spotify. This
        #      resolves issues with minor formatting differences and special characters.
        #   3) Pass only the transformed title, then manually match the artist against
        #      the returned results. this is a last-resort, as it is only accurate in
        #      cases where the first two searches fail.
        # The reason for executing all heuristics is that each fails in certain cases,
        # and by executing all three, we ensure that the maximum number of tracks are
        # matched. Unfortunately, this means sacrificing speed for accuracy, since
        # Spotify is really slow at returning search results.

        result = spotify.search('artist:%s track:%s' % (artist, title), type='track')

        track = None

        if result['tracks']['total'] > 0:
            # no additional heuristics needed
            track = result['tracks']['items'][0]
        else:
            # we'll try transforming the artist and title
            artist = sanitize_artist(artist)
            title = sanitize_title(title)

            result = spotify.search('artist:%s track:%s' % (artist, title), type='track')
            
            if result['tracks']['total'] > 0:
                # no additional heuristics needed
                track = result['tracks']['items'][0]
            else:
                # search by song title only, then match the artist after the fact
                result = spotify.search('track:%s' % title, type='track')
                if result['tracks']['total'] > 0:
                    for item in result['tracks']['items']:
                        for listed_artist in item['artists']:
                            if listed_artist['name'].lower() == artist.lower():
                                track = item
                                break
                        if track != None:
                            break

                if track == None:
                    # can't find it, period
                    failed += 1
                    failed_songs.append(song)
                    continue

        spotify_ids[local_id] = track['id']

        found += 1

    print()

    print("Found %d tracks on Spotify." % found)
    print("Failed to find %d tracks." % failed)

    if failed > 0:
        unmatched_json = {
            'songs': [
                {
                    'artist': song.artist,
                    'title': song.title,
                    'album': song.album,
                    'in_playlists': [pl.name for pl in song.playlists],
                } for song in failed_songs
            ]
        }

        with open('unmatched.json', 'w') as unmatched_file:
            json.dump(unmatched_json, unmatched_file, indent=2)

        print("Wrote unmatched song info to unmatched.json.")

    print("Adding matched songs to Spotify library...")

    #spotify.current_user_saved_tracks_add()

if __name__ == '__main__':
    print("Spotify username: ", end='')
    user = input()

    print("Spotify client ID: ", end='')
    client_id = input()

    client_secret = getpass("Spotify client secret: ")

    with open('output_library.json', 'r') as json_file:
        import_library_from_json(user, client_id, client_secret, json_file)
