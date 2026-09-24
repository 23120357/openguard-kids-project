"""Visible console simulator for week-one integration. No monitoring or enforcement."""

import argparse
import time
import uuid
from urllib.parse import urlsplit

import httpx

from agent.cache import PolicyCache


class Simulator:
    def __init__(self, client, cache):
        self.client = client
        self.cache = cache
        self.tokens = None
        self.refresh_at = 0

    def enroll(self, code, name="Lab device"):
        result = self.client.post(
            "/api/enroll",
            json={
                "code": code.strip().upper(),
                "display_name": name,
                "fingerprint": str(uuid.uuid4()),
            },
        )
        result.raise_for_status()
        self.set_tokens(result.json())

    def set_tokens(self, tokens):
        self.tokens = tokens
        self.refresh_at = time.monotonic() + tokens["expires_in"] - 60

    def refresh(self):
        result = self.client.post(
            "/api/auth/device/refresh",
            json={
                "device_id": self.tokens["device_id"],
                "refresh_token": self.tokens["refresh_token"],
            },
        )
        result.raise_for_status()
        self.set_tokens(result.json())

    def request(self, method, path, **kwargs):
        if self.tokens is None:
            raise RuntimeError("Enroll first")
        if time.monotonic() >= self.refresh_at:
            self.refresh()
        headers = {"Authorization": "Bearer " + self.tokens["access_token"]}
        result = self.client.request(method, path, headers=headers, **kwargs)
        if result.status_code == 401:
            self.refresh()
            headers["Authorization"] = "Bearer " + self.tokens["access_token"]
            result = self.client.request(method, path, headers=headers, **kwargs)
        result.raise_for_status()
        return result.json()

    def tick(self):
        cached = self.cache.load()
        # First tick always fetches: a cache might belong to an older enrollment.
        version = (
            cached["version"]
            if cached and cached.get("device_id") == self.tokens["device_id"]
            else 0
        )
        heartbeat = self.request("POST", "/api/heartbeat", json={"policy_version": version})
        if version != heartbeat["policy_version"]:
            policy = self.request("GET", "/api/policy")
            policy["device_id"] = self.tokens["device_id"]
            self.cache.save(policy)
        return heartbeat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--name", default="Lab device")
    parser.add_argument("--cache", default="data/agent/policy.db")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--show-cache", action="store_true")
    args = parser.parse_args()
    cache = PolicyCache(args.cache)
    if args.show_cache:
        print(cache.load() or "No cached policy.")
        return
    url = urlsplit(args.server)
    if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1"):
        parser.error(
            "This simulator supports HTTP loopback only; TLS/pinning is a later milestone."
        )
    print("OpenGuard Kids — VISIBLE DEVELOPMENT SIMULATOR")
    print("Only enrollment, heartbeat and policy sync. No activity monitoring or blocking.")
    print("Keep this console visible. Ctrl+C stops the simulator.")
    code = input("Enrollment code from parent dashboard: ")
    try:
        with httpx.Client(base_url=args.server, timeout=10, trust_env=False) as client:
            simulator = Simulator(client, cache)
            simulator.enroll(code, args.name)
            print("Enrolled. Credentials stay in memory; restart requires a new code.")
            while True:
                started = time.monotonic()
                try:
                    result = simulator.tick()
                    print("Connected. Server policy version:", result["policy_version"])
                except httpx.HTTPStatusError as exc:
                    print("Server rejected request:", exc.response.status_code)
                    return
                except httpx.RequestError:
                    print("Offline. Cached policy preserved; retry on next heartbeat.")
                    if args.once:
                        raise SystemExit(1)
                if args.once:
                    return
                time.sleep(max(0, 60 - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    except httpx.HTTPError:
        raise SystemExit("Could not enroll. Check server and generate a fresh enrollment code.")


if __name__ == "__main__":
    main()
