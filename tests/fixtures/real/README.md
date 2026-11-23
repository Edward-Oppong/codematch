# Real SportyBet responses for the audit tests

Drop files exported from SportyBet here (the console code's downloaded `.json` files, or HAR exports): games
fetched in full, league fetches, booking codes, finished games. `tests/test_audit.py` reads every game in them and
checks the app's reading of each market against SportyBet's own prices (correct-score bounds, double chance,
refund picks, the reliability rule, margins). Nothing here is sent anywhere; the files only feed the tests.

Good to have: games from several leagues, one league fetch, one game with suspended markets, one finished game.
