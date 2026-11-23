import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    DB_PATH = os.environ.get("CODEMATCH_DB", os.path.join(ROOT, "data", "codematch.db"))
    MAX_CONTENT_LENGTH = 400 * 1024 * 1024     # a whole league's games, or a HAR export, can be 100+ MB
    MAX_FORM_MEMORY_SIZE = 60 * 1024 * 1024    # big pastes into the import box
    SECRET_KEY = os.environ.get("CODEMATCH_SECRET", "dev-only-change-me")
    # names the app answers to; set CODEMATCH_HOST or CODEMATCH_ALLOWED_HOSTS to listen elsewhere
    extra_hosts = set()
    if os.environ.get("CODEMATCH_HOST"):
        extra_hosts.add(os.environ["CODEMATCH_HOST"].lower())
    if os.environ.get("CODEMATCH_ALLOWED_HOSTS"):
        extra_hosts.update(h.strip().lower() for h in os.environ["CODEMATCH_ALLOWED_HOSTS"].split(","))
    ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"} | extra_hosts
