from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

@dataclass(frozen=True)
class OptionQuote:
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_pct_of_mid(self) -> Decimal:
        if self.mid <= 0:
            return Decimal("999")
        return self.spread / self.mid

def price_walk(
    quote: OptionQuote,
    *,
    side: str,
    increment: Decimal,
    max_slippage_pct: Decimal,
) -> list[Decimal]:
    side = side.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if increment <= 0:
        raise ValueError("increment must be positive")

    start = quote.mid
    natural = quote.ask if side == "buy" else quote.bid
    direction = Decimal("1") if side == "buy" else Decimal("-1")
    max_move = start * max_slippage_pct

    prices: list[Decimal] = []
    current = start
    while True:
        rounded = current.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not prices or prices[-1] != rounded:
            prices.append(rounded)

        if side == "buy" and current >= natural:
            break
        if side == "sell" and current <= natural:
            break

        nxt = current + (direction * increment)
        if abs(nxt - start) > max_move:
            break
        current = min(nxt, natural) if side == "buy" else max(nxt, natural)

    return prices
