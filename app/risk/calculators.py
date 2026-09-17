from decimal import Decimal

MULTIPLIER = Decimal("100")

def long_option_max_loss(premium_per_share: Decimal, contracts: int) -> Decimal:
    return premium_per_share * MULTIPLIER * contracts

def debit_spread_max_loss(net_debit_per_share: Decimal, contracts: int) -> Decimal:
    return net_debit_per_share * MULTIPLIER * contracts

def credit_vertical_max_loss(width: Decimal, net_credit_per_share: Decimal, contracts: int) -> Decimal:
    per_share = width - net_credit_per_share
    if per_share <= 0:
        raise ValueError("Spread width must exceed net credit.")
    return per_share * MULTIPLIER * contracts

def cash_secured_put_max_loss(strike: Decimal, credit_per_share: Decimal, contracts: int) -> Decimal:
    per_share = strike - credit_per_share
    if per_share <= 0:
        raise ValueError("Strike must exceed credit.")
    return per_share * MULTIPLIER * contracts
