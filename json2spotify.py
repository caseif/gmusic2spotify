#!/usr/bin/python3

from getpass import getpass
from http.server import SimpleHTTPRequestHandler, HTTPServer
from multiprocessing import Process
from os import fdopen, pipe
import subprocess
import sys
from threading import Thread

import spotipy
from spotipy.util import prompt_for_user_token

class CustomHTTPServer(HTTPServer):
    def __init__(self, uri_pipe_write_fd, *args, **kw):
        HTTPServer.__init__(self, *args, **kw)
        self.uri_pipe_write_fd = uri_pipe_write_fd

class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        print("GET")
        self._set_headers()
        out_file = fdopen(self.server.uri_pipe_write_fd, 'w')
        out_file.write('http://localhost:8000')
        out_file.write(self.path)
        out_file.write('\n')
        exit(0)

def start_http_server(uri_pipe_write_fd):
    httpd = CustomHTTPServer(uri_pipe_write_fd, ('localhost', 8000), CustomHTTPRequestHandler)
    print("Started HTTP server on port %d." % httpd.socket.getsockname()[1])
    httpd.serve_forever()

def start_user_token_proc(uri_in, token_out, username, scope, client_id, client_secret, redirect_uri):
    # set stdin for the process to the uri pipe so we can read it directly from the HTTP thread
    sys.stdin = fdopen(uri_in, 'r')

    # call the spotipy function for obtaining the token
    # the function will read from the URI pipe we assigned to stdin, so it won't block
    token = prompt_for_user_token(username, scope, client_id, client_secret, redirect_uri)

    # open the token pipe
    token_out_file = fdopen(token_out, 'w')

    # write the token, if we successfully obtained it
    if token:
        token_out_file.write(token)

    # write a newline to signify end of transmission
    token_out_file.write('\n')

    # the process has now outlived its purpose
    exit(0)

def authenticate(username, client_id, client_secret, scope):
    # create a new pipe for passing the URI from the HTTP thread to the authentication process
    uri_pipe_read_fd, uri_pipe_write_fd = pipe()

    # create a new pipe for passing the token from the authentication process to the main thread
    token_pipe_read_fd, token_pipe_write_fd = pipe()

    # start an HTTP server for intercepting the redirect by Spotify
    http_thread = Thread(target=start_http_server, args=(uri_pipe_write_fd,))
    http_thread.start()

    # start the token prompt in a new process so we can set the stdin
    token_proc = Process(target=start_user_token_proc, args=(uri_pipe_read_fd, token_pipe_write_fd, username, scope, client_id, client_secret, 'http://localhost:8000'))
    token_proc.start()

    # open the token pipe end and read the token from it
    token_pipe_read = fdopen(token_pipe_read_fd, 'r')

    # read the token from the pipe (written by token_proc)
    token = token_pipe_read.readline()

    if not token:
        print("Failed to get Spotify token!")
        exit(-1)

    print("Successfully got Spotify token. (scope: %s)" % scope)

def import_library_from_json(username, client_id, client_secret, json_input):
    authenticate(username, client_id, client_secret, 'user-library-modify')

if __name__ == '__main__':
    print("Spotify username: ", end='')
    user = input()

    print("Spotify client ID: ", end='')
    client_id = input()

    client_secret = getpass("Spotify client secret: ")

    with open('output_library.json', 'r') as json_file:
        import_library_from_json(user, client_id, client_secret, json_file)
