#!/usr/bin/python3

from getpass import getpass
from http.server import SimpleHTTPRequestHandler, HTTPServer
from os import fdopen, pipe
import subprocess
import sys
import threading

import spotipy
from spotipy.util import prompt_for_user_token

class CustomHTTPServer(HTTPServer):
    def __init__(self, pipe_out, *args, **kw):
        HTTPServer.__init__(self, *args, **kw)
        self.pipe_out = pipe_out

class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        self._set_headers()
        out_file = fdopen(self.server.pipe_out, 'w')
        out_file.write('http://localhost:8000')
        out_file.write(self.path)
        out_file.write('\n')
        exit(0)

def start_http_server(pipe_out):
    httpd = CustomHTTPServer(pipe_out, ('localhost', 8000), CustomHTTPRequestHandler)
    print("Started HTTP server on port %d." % httpd.socket.getsockname()[1])
    httpd.serve_forever()

def import_library_from_json(username, client_id, client_secret, json_input):
    # create a new pipe
    pipe_read, pipe_write = pipe()
    
    # open the ends
    pipe_in = fdopen(pipe_read, 'r')

    # start an HTTP server for intercepting the redirect by Spotify
    http_thread = threading.Thread(target=start_http_server, args=(pipe_write,))
    http_thread.start()

    # start the token prompt in a new thread so we can kill it before it terminates
    token_thread = threading.Thread(target=prompt_for_user_token, args=(username, 'user-library-read', client_id, client_secret, 'http://localhost:8000'))
    token_thread.start()

    response = pipe_in.readline()

    code = sp_oauth.parse_response_code(response)
    token_info = sp_oauth.get_access_token(code)

    if not token_info:
        print("Failed to get Spotify token!")
        exit(-1)

    token = token_info[0]

    print("token: %s" % token)

if __name__ == '__main__':
    print("Spotify username: ", end='')
    user = input()

    print("Spotify client ID: ", end='')
    client_id = input()

    client_secret = getpass("Spotify client secret: ")

    with open('output_library.json', 'r') as json_file:
        import_library_from_json(user, client_id, client_secret, json_file)
