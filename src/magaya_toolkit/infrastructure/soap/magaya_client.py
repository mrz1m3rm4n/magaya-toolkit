"""zeep-based adapter for the Magaya SOAP API.

STATUS: scaffold. The real WSDL binding and the exact method signatures come
from the Magaya API reference (StartSession, EndSession, SetTransaction, ...).
We wire those once we have the WSDL URL and have confirmed the auth flow.

The class already implements the `MagayaApi` port so the rest of the app can
depend on it today and we only fill in the body.
"""

from __future__ import annotations

from dataclasses import dataclass

from magaya_toolkit.domain.errors import ApiError


@dataclass
class MagayaConfig:
    wsdl_url: str
    username: str
    password: str
    network_id: str


class ZeepMagayaClient:
    def __init__(self, config: MagayaConfig) -> None:
        self._config = config
        self._client = None  # lazy zeep.Client, created on first use
        self._token: str | None = None

    def start_session(self) -> str:
        # TODO: build zeep.Client(config.wsdl_url) and call StartSession with
        # the Magaya credentials; store and return the session token.
        raise ApiError("StartSession not implemented yet — pending WSDL wiring.")

    def end_session(self) -> None:
        # TODO: call EndSession with self._token.
        raise ApiError("EndSession not implemented yet — pending WSDL wiring.")

    def set_transaction(self, xml: bytes) -> str:
        # TODO: call SetTransaction with the session token + XML payload.
        raise ApiError("SetTransaction not implemented yet — pending WSDL wiring.")
