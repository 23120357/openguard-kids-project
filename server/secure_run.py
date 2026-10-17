"""Run the development server with TLS 1.2+ for a LAN/lab deployment."""

import argparse
import ssl

import uvicorn


def tls12_context(_config, default_factory):
    context = default_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", required=True, help="PEM certificate chain")
    parser.add_argument("--key", required=True, help="PEM private key")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(
        "server.app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
        ssl_context_factory=tls12_context,
    )


if __name__ == "__main__":
    main()
