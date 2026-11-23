"""Start CodeMatch:  python run.py   then open http://localhost:5000

The app only listens on this computer (127.0.0.1) and runs with debug mode off. Debug mode shows an interactive
error page that lets whoever sees it run code on this machine, so only turn it on while developing, and never
together with a public address:

    CODEMATCH_DEBUG=1 python run.py          (Windows PowerShell: $env:CODEMATCH_DEBUG=1; python run.py)
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("CODEMATCH_DEBUG") == "1"
    host = os.environ.get("CODEMATCH_HOST", "127.0.0.1")
    if debug and host not in ("127.0.0.1", "localhost"):
        raise SystemExit("Refusing to start: debug mode on a non-local address would let others run code here.")
    port = int(os.environ.get("CODEMATCH_PORT", "5000"))
    if os.environ.get("CODEMATCH_OPEN") == "1" and os.environ.get("WERKZEUG_RUN_MAIN") is None:
        # open the browser once the server answers (start.bat / start.sh set CODEMATCH_OPEN)
        import threading
        import time
        import urllib.request
        import webbrowser

        def open_when_ready(url=f"http://127.0.0.1:{port}/"):
            for _ in range(60):
                try:
                    urllib.request.urlopen(url, timeout=1)
                    webbrowser.open(url)
                    return
                except OSError:
                    time.sleep(0.5)

        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        app.run(host=host, port=port, debug=debug)
    except OSError as e:
        raise SystemExit(f"Couldn't start on port {port} ({e}). Is CodeMatch already running? If so, just open "
                         f"http://127.0.0.1:{port}/ in your browser. Otherwise set CODEMATCH_PORT to another number.")
