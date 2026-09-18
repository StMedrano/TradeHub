import json
import os
from pathlib import Path

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class JsonOAuthStorage:
    """Persistent MCP OAuth storage for Robinhood.

    The file contains access/refresh tokens and dynamic client registration data.
    It must never be committed to Git.
    """

    def __init__(self, path: str):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path)
        os.chmod(self.path, 0o600)

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._read().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump(mode="json")
        self._write(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["client_info"] = client_info.model_dump(mode="json")
        self._write(data)

    def exists(self) -> bool:
        data = self._read()
        return bool(data.get("tokens") and data.get("client_info"))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
