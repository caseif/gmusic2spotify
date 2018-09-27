from http.server import SimpleHTTPRequestHandler, HTTPServer
from multiprocessing import Process
from os import devnull, fdopen, pipe
from select import select
import signal
import sys

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
        out_file.close()
        exit(0)

    def log_message(self, format, *args):
        return

def start_http_server(uri_pipe_write_fd):
    # trash stdout so we don't spam the console with HTTP logs
    sys.stdout = open(devnull, 'w')

    httpd = CustomHTTPServer(uri_pipe_write_fd, ('localhost', 8000), CustomHTTPRequestHandler)
    httpd.serve_forever()

def start_user_token_proc(uri_in, token_out, username, scope, client_id, client_secret, redirect_uri):
    # set stdin for the process to the uri pipe so we can read it directly from the HTTP thread
    sys.stdin = fdopen(uri_in, 'r')

    signal.signal(signal.SIGTERM, sys.stdin.close)

    # trash stdout since prompt_for_user_token is pretty spammy
    sys.stdout = open(devnull, 'w')

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

    token_out_file.close()

    # the process has now outlived its purpose
    exit(0)

def authenticate(username, client_id, client_secret, scope):
    # create a new pipe for passing the URI from the HTTP thread to the authentication process
    uri_pipe_read_fd, uri_pipe_write_fd = pipe()

    # create a new pipe for passing the token from the authentication process to the main thread
    token_pipe_read_fd, token_pipe_write_fd = pipe()

    # start an HTTP server for intercepting the redirect by Spotify
    http_proc = Process(target=start_http_server, args=(uri_pipe_write_fd,))
    http_proc.daemon = True
    http_proc.start()

    # start the token prompt in a new process so we can set the stdin
    token_proc = Process(target=start_user_token_proc, args=(uri_pipe_read_fd, token_pipe_write_fd, username, scope, client_id, client_secret, 'http://localhost:8000'))
    token_proc.daemon = True
    token_proc.start()

    # open the token pipe end and read the token from it
    token_pipe_read = fdopen(token_pipe_read_fd, 'r')

    # read the token from the pipe (written by token_proc)
    r, w, e = select([token_pipe_read], [], [], 30)
    if not token_pipe_read in r:
        print("Failed to get Spotify token! (timeout)")
        exit(-1)

    # read the token from token_prompt, making sure to omit the newline from the end
    token = token_pipe_read.readline()[:-1]

    token_pipe_read.close()

    if not token:
        print("Failed to get Spotify token! (empty)")
        exit(-1)

    http_proc.terminate()
    token_proc.terminate()

    print("Successfully acquired Spotify token. (scope: %s)" % scope)

    return token

if __name__ == "__main__":
    print("This file contains a library and cannot be run from the CLI.")
    exit(-1)