import httpx


def get_json(url: str) -> dict:
    with httpx.Client(timeout=10) as client:
        return client.get(url).raise_for_status().json()
