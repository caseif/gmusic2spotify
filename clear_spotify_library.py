#!/usr/bin/python3

from getpass import getpass

import spotipy

from spotify_auth import authenticate


def clear_library(username, client_id, client_secret):
    library_mod_token = authenticate(username, client_id, client_secret,
                                     'user-library-read user-library-modify playlist-modify-public '
                                     'playlist-read-private playlist-modify-private')

    print("Creating Spotify API instance...")

    spotify = spotipy.Spotify(auth=library_mod_token)

    print("Removing saved tracks...")

    cur_count = -1
    total = 0

    while cur_count != 0:
        res = spotify.current_user_saved_tracks(limit=50)
        
        items = res['items']
        cur_count = len(items)
        total += cur_count

        if cur_count == 0:
            break

        ids = [item['track']['id'] for item in items]

        spotify.current_user_saved_tracks_delete(tracks=ids)

    print("Removing %d saved tracks." % total)

    print("Removing user playlists...")

    cur_count = -1
    total = 0

    while cur_count != 0:
        res = spotify.user_playlists(username, limit=50)

        items = res['items']
        cur_count = len(items)
        total += cur_count

        if cur_count == 0:
            break

        for item_id in [item['id'] for item in items]:
            spotify.user_playlist_unfollow(user, item_id)
    
    print("Removed %d playlists." % total)


if __name__ == "__main__":
    user = input('Spotify username: ')
    client_id = input('Spotify client ID: ')
    client_secret = getpass('Spotify client secret: ')

    print("This action will IRREVERSIBLY clear your Spotify playlists and saved tracks!")
    confirmation = input("Type yes to confirm this action: ")
    if confirmation.lower() != "yes":
        print("Did not receive confirmation; aborting.")
        exit(0)
    
    print("Continuing...")

    clear_library(user, client_id, client_secret)
