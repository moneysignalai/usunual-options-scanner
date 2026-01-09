from src.massive_client import MassiveClient
from src.config import load_settings


def main() -> None:
    settings = load_settings()
    client = MassiveClient(settings=settings)
    for symbol in ["SPY", "QQQ", "NVDA"]:
        snap = client.get_option_chain_snapshot(symbol, limit=25)
        print(symbol, len(snap.results))
        for c in snap.results[:5]:
            print(c.details.ticker, c.details.strike_price, c.details.expiration_date)
    client.close()


if __name__ == "__main__":
    main()
