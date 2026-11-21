"""Formatting helpers for the prototype Compute Points wallet."""
from dataclasses import dataclass

@dataclass(frozen=True)
class WalletTransaction:
    amount: int
    reason: str
    created_at: str

@dataclass
class WalletSummary:
    balance: int
    transactions: list[WalletTransaction]

    def formatted_balance(self) -> str:
        return f"{self.balance:,} CP".replace(",", ".")

    def recent_transactions(self, limit: int = 20) -> list[WalletTransaction]:
        return self.transactions[:max(0, limit)]
