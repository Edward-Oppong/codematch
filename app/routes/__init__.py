"""One blueprint per section: codes, leagues, games, imports."""
import datetime
import time


def now_ms():
    return int(time.time() * 1000)


def back_to(target, default):
    """Where to return after a form: only a path inside this app, never another site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def num(args, key, default):
    try:
        v = args.get(key)
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def day_range(args, default_days=2):
    """(start date, end date, start ms, end ms) from ?start=YYYY-MM-DD&end=YYYY-MM-DD, in UTC (Ghana time).
    The end date is included. Defaults to today and the next default_days days."""
    today = datetime.datetime.now(datetime.timezone.utc).date()

    def parse(key, default):
        try:
            return datetime.date.fromisoformat(args.get(key) or "")
        except ValueError:
            return default

    start = parse("start", today)
    end = parse("end", start + datetime.timedelta(days=default_days))
    if end < start:
        start, end = end, start
    to_ms = lambda d: int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    return start, end, to_ms(start), to_ms(end + datetime.timedelta(days=1))
