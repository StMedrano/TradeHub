from dataclasses import dataclass

@dataclass(frozen=True)
class Alert:
    severity: str
    title: str
    message: str
    underlying: str | None = None

class AlertService:
    """Boundary for Twilio/Pushover pages."""

    async def page(self, alert: Alert) -> None:
        return None
