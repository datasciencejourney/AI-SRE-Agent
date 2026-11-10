import hashlib


def make_fingerprint(service: str, alert_name: str) -> str:
    """Same service + same alert name means same problem."""
    return hashlib.sha256(f"{service}|{alert_name}".encode()).hexdigest()
