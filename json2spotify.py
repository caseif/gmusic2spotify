#!/usr/bin/python3

from collections import OrderedDict
import csv
from datetime import datetime, time, timedelta
from difflib import SequenceMatcher
from getpass import getpass
import json
from math import ceil
from os import path
import re
from sys import stdout
from uuid import UUID

import spotipy
from spotipy.util import prompt_for_user_token

from spotify_auth import authenticate

# the minimum similarity for an artist to be considered correct with respect to the target
ARTIST_MATCH_THRESHOLD = 0.5

###
### Regexes for transforming track/artist names to increase chance of matching
###

# apostrophes should be removed entirely (instead of replaced by spaces)
APOS_REGEX = re.compile('\'')
# most non-alphanumeric characters cause problems, and they don't provide any disambiguation
NON_AN_REGEX = re.compile('[^A-Za-zÀ-ÿ0-9-_ ]')
# a mismatch in the leading "the" in track/artist names is a common point of failure
THE_REGEX = re.compile('^The ')

# all of the following regexes are usually used to separate multiple artists
# it's usually "good enough" to only search for the first artist -
#     it usually only fails when a featured artist or remixer isn't properly credited as an artist
COMMA_REGEX = re.compile(', (.*)')
AMP_REGEX = re.compile(' & (.*)')
X_REGEX = re.compile(' x (.*)')
VS_REGEX = re.compile(' vs\\.? (.*)')

# a mismatch in whether the featured artist is credited in the track name is a common point of failure
FEAT_REGEX = re.compile(r' [\(\[][Ff](ea)?t\.? (.*)[\)\]]')

class Song:
    def __init__(self, id, artist, title, album, in_library):
        self.id = id
        self.artist = artist
        self.title = title
        self.album = album
        self.in_library = in_library
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
        if not song in self.songs:
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

def unique(l):
    seen = set()
    ul = []
    for x in l:
        if x not in seen:
            ul.append(x)
            seen.add(x)
    return ul



def sanitize_field(v):
    return re.sub(THE_REGEX, '', re.sub(NON_AN_REGEX, ' ', re.sub(APOS_REGEX, '', v)))

def sanitize_artist(v):
    return sanitize_field(re.sub(VS_REGEX, '', re.sub(X_REGEX, '', re.sub(AMP_REGEX, '', re.sub(COMMA_REGEX, '', v)))))

def sanitize_title(v):
    return sanitize_field(re.sub(FEAT_REGEX, '', v))

def pick_best_result(artist, title, album, result):
    if result['tracks']['total'] == 0:
        return None

    best_match = None
    best_score = 0
    for cur_track in result['tracks']['items']:
        # if we can't find "Remix" in both, skip
        if ('Remix' in cur_track['name']) != ('Remix' in title):
            continue

        best_artist_score = 0

        for cur_artist in cur_track['artists']:
            score = SequenceMatcher(a=artist, b=cur_artist['name']).ratio()
            if score > best_artist_score:
                best_artist_score = score

        # probably the wrong artist
        if best_artist_score < ARTIST_MATCH_THRESHOLD:
            continue

        # we compute the similarity of the artist, title, and album and pick the best
        score =  (best_artist_score
                + SequenceMatcher(a=title,  b=cur_track['name']).ratio()
                + SequenceMatcher(a=album,  b=cur_track['album']['name']).ratio()) / 3

        if score > best_score:
            best_score = score
            best_match = cur_track
    
    return best_match

def import_library_from_json(username, client_id, client_secret, json_input):
    library_mod_token = authenticate(username, client_id, client_secret, 'user-library-modify playlist-modify-private')

    print("Creating Spotify API instance...")

    spotify = spotipy.Spotify(auth=library_mod_token)

    print("Loading library JSON...")

    library_json = json.load(json_input)

    song_list = library_json['songs']

    songs = {}

    print("Ingesting song list...")

    for uuid, serial in song_list.items():
        songs[UUID(uuid)] = Song(uuid, serial['artist'], serial['title'], serial['album'], serial['in_library'])

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

    MAPPINGS_FILE_NAME = 'spotify_mappings.csv'

    if path.isfile(MAPPINGS_FILE_NAME):
        print("Using local mappings file.")
        with open(MAPPINGS_FILE_NAME, 'r') as mappings_file:
            reader = csv.reader(mappings_file)
            for row in reader:
                spotify_ids[row[0]] = row[1]
    else:
        print("Matching songs on Spotify...")

        MAX_SPEEDS = 50

        speeds = []
        last_search = None
        last_speed_update = None
        i = 0

        eta = 0
        for local_id, song in songs.items():
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
            album = song.album

            # We have three different levels of heuristics which we use to match tracks:
            #   1) Pass the artist and title as-is, and hope Spotify turns something up.
            #   2) Transform the artist and title, then pass them on to spotify. This
            #      resolves issues with minor formatting differences and special characters.
            #   3) Pass only the transformed title, then manually match the artist against
            #      the returned results. This is a last-resort, as it is only accurate in
            #      cases where the first two searches fail.
            # The reason for executing all heuristics is that each fails in certain cases,
            # and by executing all three, we ensure that the maximum number of tracks are
            # matched. Unfortunately, this means sacrificing speed for accuracy, since
            # Spotify is really slow at returning search results.

            result = spotify.search('artist:%s track:%s' % (artist, title), type='track')

            track = pick_best_result(artist, title, album, result)

            if not track:
                # we'll try transforming the artist and title
                artist = sanitize_artist(artist)
                title = sanitize_title(title)

                result = spotify.search('artist:%s track:%s' % (artist, title), type='track')

                track = pick_best_result(artist, title, album, result)

            if not track:
                # search by song title only, then match the artist after the fact
                result = spotify.search('track:%s' % title, type='track')
                
                track = pick_best_result(artist, title, album, result)

            if not track:
                # can't find it
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

        with open(MAPPINGS_FILE_NAME, 'w+') as mappings_file:
            writer = csv.writer(mappings_file)

            for k, v in spotify_ids.items():
                writer.writerow([k, v])
            
            print("Wrote Spotify ID mappings to %s." % MAPPINGS_FILE_NAME)

    spotify_songs = unique({k:v for k, v in spotify_ids.items() if songs[k if k is UUID else UUID(k)].in_library}.values())

    print("Adding %d matched songs to Spotify library..." % len(spotify_songs))

    PER_REQUEST = 50

    for i in range(0, ceil(len(spotify_songs) / PER_REQUEST)):
        songs_slice = spotify_songs[(i * PER_REQUEST):min((i + 1) * PER_REQUEST, len(spotify_songs))]

        if len(songs_slice) == 0:
            break

        spotify.current_user_saved_tracks_add(songs_slice)

    print("Finished adding songs to library.")

    print("Generating %d playlists..." % len(playlists))

    for playlist in playlists:
        playlist_id = spotify.user_playlist_create(user, playlist.name, public=False)['id']

        for i in range(0, ceil(len(playlist.songs) / PER_REQUEST)):
            songs_slice = [
                spotify_ids[song.id]
                    for song in playlist.songs[(i * PER_REQUEST):min((i + 1) * PER_REQUEST, len(playlist.songs))]
                    if song.id in spotify_ids
            ]

            if len(songs_slice) == 0:
                break

            spotify.user_playlist_add_tracks(user, playlist_id, songs_slice)

    print("Finished generating playlists.")

    print("Done!")

if __name__ == '__main__':
    user = input('Spotify username: ')
    client_id = input('Spotify client ID: ')
    client_secret = getpass('Spotify client secret: ')

    print("secret!!!: <<%s>>" % client_secret)

    with open('output_library.json', 'r') as json_file:
        import_library_from_json(user, client_id, client_secret, json_file)
