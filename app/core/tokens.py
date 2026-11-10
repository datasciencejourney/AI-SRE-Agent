"""HMAC helpers. Used for the webhook signature and for approval tokens.

Kept free of any app imports so the MCP servers can use it too.
"""
import hashlib
import hmac


def sign(secret: str, message: str | bytes) -> str:
    if isinstance(message, str):
        message = message.encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, message: str | bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(secret, message), signature)


def approval_message(incident_id: str, action_type: str, target: str) -> str:
    return f"{incident_id}|{action_type}|{target}"
