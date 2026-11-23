"""Look at one saved game response from the command line.

    python scripts/analyse_game.py game.json                       most likely picks per zone
    python scripts/analyse_game.py game.json "Home Total: Over 1.5"  safer / riskier picks around one pick
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis import markets, picks                      # noqa: E402
from app.analysis.alternatives import alternatives            # noqa: E402
from app.sources.sportybet.importer import extract_all_json   # noqa: E402


def fmt(k, v):
    return (f"{k:38} odds {v['odds']:>6.2f}  chance {v['prob'] * 100:5.1f}%  return {v['ret']:.3f}"
            f"  {picks.ZONE_LABEL[picks.zone(v['odds'])]}")


def main(path, pick=None):
    ev = extract_all_json(open(path, encoding="utf-8", errors="replace").read())[0]["data"]
    priced = markets.priced_all(ev)
    print(f"{ev['homeTeamName']} v {ev['awayTeamName']}: {len(priced)} picks modelled\n")
    if pick:
        fam = priced[pick]["family"]
        fp = markets.build_priced(ev, fam)
        print("PICK  ", fmt(pick, fp[pick]), "\n")
        s, r = alternatives(fp, pick)
        print("SAFER (win whenever your pick wins):")
        for k, v in s[:10]:
            print("  ", fmt(k, v))
        print("\nRISKIER (win only on some of your pick's results):")
        for k, v in r[:6]:
            print("  ", fmt(k, v))
        return
    for key, label, lo, hi in picks.ZONES:
        rows = sorted(((k, v) for k, v in priced.items() if picks.zone(v["odds"]) == key), key=lambda kv: -kv[1]["prob"])
        print(f"{label} ({len(rows)} picks), most likely first:")
        for k, v in rows[:5]:
            print("  ", fmt(k, v))
        print()
    print("Best return of any pick:", f"{max(v['ret'] for v in priced.values()):.3f}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
