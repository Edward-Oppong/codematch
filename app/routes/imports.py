"""Import: upload or paste what the console code downloaded (or anything copied from the Network tab).
Also clearing old data before a fresh import."""
import time

from flask import Blueprint, render_template, request

from .. import store
from ..db import get_db
from ..sources.sportybet import importer, snippets

bp = Blueprint("imports", __name__, url_prefix="/import")


def _page(msgs=()):
    from .bridge import key
    con = get_db()
    return render_template("imports/index.html", msgs=msgs, directory_snippet=snippets.directory_snippet(),
                           counts=store.counts(con), bookmarklet=snippets.bookmarklet(request.host_url, key(con)))


@bp.route("/", methods=["GET", "POST"])
def index():
    msgs = []
    if request.method == "POST":
        con = get_db()
        texts = [request.form.get("text", "")]
        for f in request.files.getlist("files"):
            if f and f.filename:
                texts.append(f.read().decode("utf-8", errors="replace"))
        for t in texts:
            if t.strip():
                msgs += importer.import_text(con, t)
        if not msgs:
            msgs = [(False, "Nothing to import: choose a file or paste a response.")]
    return _page(msgs)


@bp.post("/new-key")
def new_key():
    import secrets
    store.save_settings(get_db(), bridge_key=secrets.token_urlsafe(18), bridge_used=False)
    return _page([(True, "New key made. Your old CodeMatch bookmark no longer works: delete it and drag the new one below "
                         "to your bookmarks bar.")])


@bp.post("/clear")
def clear():
    con = get_db()
    what = request.form.get("what")
    if what == "old_games":
        n = store.delete_events(con, before_ms=int(time.time() * 1000) - 86400000)
        msgs = [(True, f"Deleted {n} games that kicked off more than a day ago.")]
    elif what == "games":
        n = store.delete_events(con)
        msgs = [(True, f"Deleted all {n} games and imported leagues. Codes are kept.")]
    elif what == "everything":
        n_codes, n_games = store.delete_everything(con)
        msgs = [(True, f"Deleted {n_codes} codes and {n_games} games. The league directory is kept.")]
    else:
        msgs = [(False, "Nothing deleted.")]
    return _page(msgs)
