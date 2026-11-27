"""CodeMatch: review SportyBet booking codes, leagues and games with the bookmaker's own odds.

Three sections: Codes (review booking codes), Leagues (every game in the leagues and dates you choose)
and Games (one game, every market). Data comes in through Import; the app never contacts SportyBet.
"""
import datetime
import time

from flask import Flask
from markupsafe import Markup

from .config import Config
from .db import close_db


def kickoff(ms, fmt="%a %d %b %H:%M"):
    """A time, written in UTC (Ghana time); the page can switch it to the viewer's own time zone."""
    if not ms:
        return "?"
    text = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime(fmt)
    return Markup('<time data-ms="%d" data-fmt="%s">%s</time>') % (int(ms), fmt, text)


def one_in(p):
    """0.0032 -> '1 in 315'. The way a small chance is easiest to feel."""
    if p is None:
        return "-"
    if p <= 0:
        return "no chance"
    if p >= 0.5:
        return f"{p * 100:.0f}%"
    n = 1 / p
    return f"1 in {n:,.0f}" if n >= 10 else f"1 in {n:.1f}".replace(".0", "")


def ago(ts):
    if not ts:
        return "never"
    s = max(0, int(time.time()) - int(ts))
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def league(name):
    """A league still known only by its id reads as such, not as 'sr:tournament:1234'."""
    return "league not named yet (fetch the league list)" if str(name or "").startswith("sr:tournament:") else name


def pct(p, digits=0):
    return "-" if p is None else f"{p * 100:.{digits}f}%"


class _HideKey:
    """Keep the bookmark's secret key out of the request lines printed in the terminal."""
    import re as _re
    pattern = _re.compile(r"([?&]k=)[^&\s\"]+")

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self.pattern.sub(r"\1(hidden)", record.msg)
        record.args = tuple(self.pattern.sub(r"\1(hidden)", a) if isinstance(a, str) else a
                            for a in (record.args or ()))
        return True


def create_app(config=None):
    import logging
    logging.getLogger("werkzeug").addFilter(_HideKey())
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    app.teardown_appcontext(close_db)
    app.jinja_env.filters.update(kickoff=kickoff, ago=ago, pct=pct, one_in=one_in, league=league)
    app.jinja_env.globals.update(now_ms=lambda: int(time.time() * 1000))

    @app.before_request
    def only_this_computer():
        """Answer only requests addressed to this computer by name (127.0.0.1, localhost) or configured hosts.
        A website can make its own name point at 127.0.0.1 ("DNS rebinding") and then talk to the app as if it were the app's own page;
        its requests still carry its own name, so they stop here."""
        from flask import abort, request
        allowed = app.config.get("ALLOWED_HOSTS", set())
        if "*" in allowed:
            return None
        host = request.host.rsplit(":", 1)[0] if not request.host.endswith("]") else request.host
        if host.lower() not in allowed:
            abort(400, "CodeMatch only answers at authorized hosts. Set CODEMATCH_ALLOWED_HOSTS or CODEMATCH_HOST.")
        return None

    @app.before_request
    def same_site_forms_only():
        """Forms that change data are only accepted from this app's own pages, so another website can't press
        delete for you in the background. (The bookmark button's calls are checked separately in bridge.py.)"""
        from flask import abort, request
        if request.method != "POST" or (request.blueprint == "bridge" and request.endpoint != "bridge.queue"):
            return None
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403)
        source = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if source and not (source.rstrip("/") + "/").startswith(request.host_url):
            abort(403)
        return None

    @app.context_processor
    def bridge_state():
        from . import store
        from .db import get_db
        st = store.settings(get_db())
        return {"button_used": bool(st.get("bridge_used")), "button_outdated": bool(st.get("button_outdated"))}

    from .routes import bridge, codes, games, imports, leagues, results, rollover
    for bp in (codes.bp, leagues.bp, games.bp, results.bp, imports.bp, bridge.bp, rollover.bp):
        app.register_blueprint(bp)
    return app
