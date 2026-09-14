"""Owner-only local OAuth bootstrap. Never run this on a public Actions runner.

Credentials are written only to the explicitly selected local output file.
Google desktop Picker grants drive.file access to the selected folder only.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlparse, parse_qs
import webbrowser
import httpx
from dsa_drive_store import SCOPE, DriveStore, StoreError, checked_id


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client-json', type=Path, required=True)
    p.add_argument('--folder-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if os.environ.get('GITHUB_ACTIONS') or a.output.exists():
        raise SystemExit('LOCAL_OWNER_ONLY_OR_OUTPUT_EXISTS')
    checked_id(a.folder_id)
    cfg = json.loads(a.client_json.read_text())['installed']
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth callback URLs contain a code: never log them.

        def do_GET(self):
            if urlparse(self.path).path != '/callback':
                self.send_error(404); return
            q = parse_qs(urlparse(self.path).query)
            if q.get('state') != [state]:
                self.send_error(403); return
            result.update(q)
            self.send_response(200); self.send_header('Content-Type', 'text/plain'); self.end_headers()
            self.wfile.write(b'You may close this tab. Check your local terminal for the result.')

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        server.timeout = 1
        redirect = 'http://127.0.0.1:' + str(server.server_port) + '/callback'
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': cfg['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
            'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'false',
            'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
            'trigger_onepick': 'true', 'allow_multiple': 'false', 'allow_folder_selection': 'true',
            'mimetypes': 'application/vnd.google-apps.folder', 'file_ids': a.folder_id})
        webbrowser.open(url)
        print('Select the specified DSA folder in Google. Credentials will not be printed.')
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if result.get('picked_file_ids') != [a.folder_id] or not result.get('code'):
        raise SystemExit('EXPECTED_FOLDER_NOT_AUTHORIZED')
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        r = c.post('https://oauth2.googleapis.com/token', data={
            'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'],
            'code': result['code'][0], 'code_verifier': verifier,
            'redirect_uri': redirect, 'grant_type': 'authorization_code'})
        if r.status_code != 200:
            raise SystemExit('OAUTH_EXCHANGE_FAILED')
        t = r.json()
        if set(t.get('scope', '').split()) != {SCOPE} or not t.get('refresh_token'):
            raise SystemExit('REFRESH_TOKEN_OR_SCOPE_INVALID')
        c.headers['Authorization'] = 'Bearer ' + t['access_token']
        try:
            DriveStore(c, a.folder_id).private_meta(a.folder_id, folder=True)
        except StoreError:
            raise SystemExit('FOLDER_PERMISSION_CHECK_FAILED') from None
    saved = {'DSA_DRIVE_CLIENT_ID': cfg['client_id'], 'DSA_DRIVE_CLIENT_SECRET': cfg['client_secret'],
             'DSA_DRIVE_REFRESH_TOKEN': t['refresh_token'], 'DSA_DRIVE_FOLDER_ID': a.folder_id}
    fd = os.open(a.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(saved, f, indent=2)
    print('AUTHORIZATION_SAVED_LOCALLY. Copy values only into GitHub Actions Secrets, never chat.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('LOCAL_AUTHORIZATION_FAILED') from None
