"""Local Sign in with ChatGPT plan usage (OAuth PKCE, one active account)."""

import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from django.conf import settings

from .https import verified_context
from .providers import ProviderError


AUTH_BASE = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTH_PATH = Path(settings.DATA_DIR) / "assistant_auth.json"
LOCK = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write(record: dict) -> None:
    AUTH_PATH.parent.mkdir(exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix="assistant_auth_", dir=AUTH_PATH.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(record, file)
        os.replace(temp_path, AUTH_PATH)
        os.chmod(AUTH_PATH, 0o600)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _post_form(url: str, fields: dict) -> dict:
    request = Request(url, data=urlencode(fields).encode("utf-8"),
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(request, timeout=20, context=verified_context()) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            details = json.loads(exc.read(8192))
        except (OSError, ValueError):
            details = {}
        error = details.get("error") if isinstance(details, dict) else None
        code = error.get("code") if isinstance(error, dict) else error
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", code) else None
        suffix = f", код {safe_code}" if safe_code else ""
        raise ProviderError(f"OpenAI отклонил завершение входа (HTTP {exc.code}{suffix}).") from exc
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc.reason):
            raise ProviderError("Не удалось проверить защищённое соединение с OpenAI. Проверьте сертификаты Python на этом компьютере.") from exc
        raise ProviderError("Нет соединения с сервером OpenAI при завершении входа. Проверьте интернет и доступ к auth.openai.com.") from exc
    except TimeoutError as exc:
        raise ProviderError("Сервер OpenAI не ответил при завершении входа. Попробуйте ещё раз.") from exc


def _get_json(url: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=20, context=verified_context()) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ProviderError("Не удалось получить данные для входа через ChatGPT.") from exc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start(request) -> str:
    with LOCK:
        record = _read()
        if not record.get("host_id"):
            record["host_id"] = f"urn:uuid:{uuid.uuid4()}"
            _write(record)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    port = request.get_port()
    redirect_uri = f"http://127.0.0.1:{port}/api/assistant/auth/callback/"
    client_id = record.get("client_id") or "dynamic_agent_client"
    request.session["assistant_oauth"] = {
        "state": state, "nonce": nonce, "verifier": verifier,
        "redirect_uri": redirect_uri, "client_id": client_id, "started": time.time(),
    }
    params = {
        "client_id": client_id,
        "ext_agent_host_id": record["host_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
    }
    if client_id == "dynamic_agent_client":
        params["agent_name_hint"] = "Кабинет репетитора"
    elif record.get("id_token"):
        params["id_token_hint"] = record["id_token"]
    return f"{AUTH_BASE}/api/accounts/authorize?{urlencode(params)}"


def finish(request) -> None:
    pending = request.session.pop("assistant_oauth", None)
    if not pending or time.time() - pending["started"] > 600:
        raise ProviderError("Время входа истекло. Начните подключение заново.")
    if not secrets.compare_digest(request.GET.get("state", ""), pending["state"]):
        raise ProviderError("Проверка входа не пройдена. Начните подключение заново.")
    if request.GET.get("error"):
        raise ProviderError("Доступ к плану ChatGPT не разрешён.")
    code = request.GET.get("code", "")
    callback_id = request.GET.get("client_id", "")
    if not code:
        raise ProviderError("ChatGPT не передал код входа.")
    if pending["client_id"] == "dynamic_agent_client":
        if not callback_id.startswith("oaiapp_"):
            raise ProviderError("ChatGPT не передал идентификатор приложения.")
        client_id = callback_id
    else:
        client_id = pending["client_id"]
        if callback_id and callback_id != client_id:
            raise ProviderError("Идентификатор приложения изменился во время входа.")
    tokens = _post_form(f"{AUTH_BASE}/api/accounts/oauth/token", {
        "grant_type": "authorization_code", "client_id": client_id,
        "code": code, "code_verifier": pending["verifier"],
        "redirect_uri": pending["redirect_uri"], "resource": RESOURCE,
    })
    if "chatgpt.tokens.use.direct" not in tokens.get("scope", "").split():
        raise ProviderError("Для приложения не разрешено использование плана ChatGPT.")
    if not all(tokens.get(key) for key in ("access_token", "refresh_token", "id_token")):
        raise ProviderError("ChatGPT вернул неполные данные входа.")
    configuration = _get_json(f"{AUTH_BASE}/.well-known/openid-configuration")
    jwks_uri = configuration.get("jwks_uri", "")
    if not jwks_uri.startswith(f"{AUTH_BASE}/"):
        raise ProviderError("Не удалось проверить подпись входа ChatGPT.")
    try:
        key = jwt.PyJWKClient(jwks_uri, ssl_context=verified_context()).get_signing_key_from_jwt(tokens["id_token"])
        claims = jwt.decode(tokens["id_token"], key.key, algorithms=["RS256", "ES256"],
                            audience=client_id, issuer=configuration["issuer"])
    except jwt.PyJWKClientConnectionError as exc:
        reason = getattr(exc.__cause__, "reason", None)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
            raise ProviderError("Не удалось проверить сертификат при загрузке ключа подписи ChatGPT.") from exc
        raise ProviderError("Не удалось загрузить ключ подписи ChatGPT. Проверьте доступ к auth.openai.com.") from exc
    except (jwt.PyJWTError, KeyError, URLError) as exc:
        raise ProviderError("Не удалось проверить токен ChatGPT. Начните вход заново.") from exc
    if claims.get("nonce") != pending["nonce"] or not claims.get("sub"):
        raise ProviderError("Проверка входа ChatGPT не пройдена.")
    with LOCK:
        record = _read()
        if record.get("subject") and record["subject"] != claims["sub"] and pending["client_id"] != "dynamic_agent_client":
            raise ProviderError("Вход выполнен в другой аккаунт ChatGPT.")
        models = _get_json(f"{RESOURCE}/models", tokens["access_token"]).get("models", [])
        available = [item for item in models if item.get("visibility") == "list" and item.get("slug")]
        if not available:
            raise ProviderError("Для аккаунта ChatGPT нет доступной модели.")
        record.update({
            "client_id": client_id, "subject": claims["sub"],
            "email": claims.get("email", ""), "id_token": tokens["id_token"],
            "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
            "scopes": tokens["scope"].split(), "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
            "model": available[0]["slug"],
        })
        _write(record)


def credentials() -> dict | None:
    with LOCK:
        record = _read()
        if not record.get("access_token") or "chatgpt.tokens.use.direct" not in record.get("scopes", []):
            return None
        if record.get("expires_at", 0) > time.time() + 120:
            return record
        if not record.get("refresh_token"):
            return None
        tokens = _post_form(f"{AUTH_BASE}/api/accounts/oauth/token", {
            "grant_type": "refresh_token", "client_id": record["client_id"],
            "refresh_token": record["refresh_token"], "resource": RESOURCE,
        })
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            raise ProviderError("Сессия ChatGPT истекла. Подключите аккаунт заново.")
        if "chatgpt.tokens.use.direct" not in tokens.get("scope", "").split():
            raise ProviderError("Доступ к плану ChatGPT больше не разрешён.")
        record.update({"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
                       "scopes": tokens["scope"].split(), "expires_at": time.time() + int(tokens.get("expires_in", 3600))})
        if tokens.get("id_token"):
            record["id_token"] = tokens["id_token"]
        _write(record)
        return record


def disconnect() -> bool:
    with LOCK:
        record = _read()
        if not record:
            return True
        revoked = True
        if record.get("refresh_token") and record.get("client_id"):
            try:
                configuration = _get_json(f"{AUTH_BASE}/.well-known/openid-configuration")
                endpoint = configuration.get("revocation_endpoint", "")
                if not endpoint.startswith(f"{AUTH_BASE}/"):
                    raise ProviderError("Не удалось проверить адрес отзыва токена.")
                request = Request(endpoint, data=urlencode({
                    "token": record["refresh_token"], "token_type_hint": "refresh_token",
                    "client_id": record["client_id"],
                }).encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
                with urlopen(request, timeout=20, context=verified_context()):
                    pass
            except (ProviderError, HTTPError, URLError, TimeoutError):
                revoked = False
        # Keep the registration/host mapping for a later reauthorization.
        for key in ("access_token", "refresh_token", "id_token", "expires_at", "scopes", "model"):
            record.pop(key, None)
        _write(record)
        return revoked
