"""TLS 1.2+ validation and exact certificate pin verification."""

from __future__ import annotations

import hashlib
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit

PIN_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TransportPolicy:
    server_url: str
    certificate_sha256: str = ""
    allow_insecure_http: bool = False

    def validate(self) -> None:
        parsed = urlsplit(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Server URL must be an absolute HTTP(S) origin")
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme == "http" and not loopback and not self.allow_insecure_http:
            raise ValueError("A remote server must use HTTPS")
        if parsed.scheme == "https" and not PIN_PATTERN.fullmatch(self.certificate_sha256.lower()):
            raise ValueError("HTTPS requires a 64-character SHA-256 certificate pin")

    def verify_peer(self, timeout: float = 10) -> None:
        self.validate()
        parsed = urlsplit(self.server_url)
        if parsed.scheme != "https":
            return
        context = tls_context()
        with (
            socket.create_connection((parsed.hostname, parsed.port or 443), timeout=timeout) as raw,
            context.wrap_socket(raw, server_hostname=parsed.hostname) as tls,
        ):
            actual = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
        if actual.lower() != self.certificate_sha256.lower():
            raise ssl.SSLError("Server certificate pin mismatch")


def tls_context() -> ssl.SSLContext:
    # The exact pinned leaf certificate is the trust anchor, which also supports
    # a self-signed lab certificate without weakening identity verification.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
