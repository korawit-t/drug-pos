"""
Production server for the shop LAN (works on Windows — gunicorn doesn't).

    python serve.py              # port 8000
    python serve.py --port 8080

Set DRUGPOS_DEBUG=0 first (scripts/windows/start-server.bat does this), and run
`python manage.py collectstatic --noinput` after every frontend build.
"""

import argparse
import os
import socket

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    parser = argparse.ArgumentParser(description="Drug POS server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    application = get_wsgi_application()
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "<ip-of-this-pc>"
    print(f"Drug POS is running: http://{ip}:{args.port}  (Ctrl+C to stop)")
    serve(application, listen=f"*:{args.port}", threads=args.threads)


if __name__ == "__main__":
    main()
