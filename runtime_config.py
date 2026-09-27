"""Local defaults; production is exposed only through an authenticated HTTPS proxy."""
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('SIGNAL_DATA_DIR', str(ROOT / 'data')))
BIND = os.environ.get('SIGNAL_BIND', '127.0.0.1')
PORT = int(os.environ.get('SIGNAL_PORT', '4317'))
PUBLIC_ORIGIN = os.environ.get('SIGNAL_PUBLIC_ORIGIN', '').rstrip('/')

def validate_origin(value):
    u = urlsplit(value)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
        raise ValueError('SIGNAL_PUBLIC_ORIGIN must be an HTTPS origin without a path')
    return u.netloc.lower()

PUBLIC_HOST = validate_origin(PUBLIC_ORIGIN) if PUBLIC_ORIGIN else None
if BIND not in ('127.0.0.1', 'localhost', '::1') and not PUBLIC_HOST:
    raise ValueError('A public bind requires SIGNAL_PUBLIC_ORIGIN and an authenticated reverse proxy')

def allowed_read(host):
    return host.lower() in {f'127.0.0.1:{PORT}', f'localhost:{PORT}', PUBLIC_HOST}

def allowed_write(host, origin, content_type):
    if not allowed_read(host) or content_type.split(';')[0].strip() != 'application/json':
        return False
    expected = PUBLIC_ORIGIN if PUBLIC_HOST and host.lower() == PUBLIC_HOST else 'http://' + host
    return origin == expected
