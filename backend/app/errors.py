from __future__ import annotations


class ProxyError(Exception):
    """Rendered as an OpenAI-style {"error": {...}} body."""

    def __init__(self, status: int, message: str, type_: str = "invalid_request_error", code: str | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.type, self.code, self.headers = status, message, type_, code, headers or {}

    def body(self) -> dict:
        return {"error": {"message": self.message, "type": self.type, "param": None, "code": self.code}}


def unauthorized(msg: str = "Invalid API key") -> ProxyError:
    return ProxyError(401, msg, "authentication_error", "invalid_api_key")


def not_found_model(model: str) -> ProxyError:
    return ProxyError(404, f"The model `{model}` does not exist or is not enabled.", "invalid_request_error", "model_not_found")
