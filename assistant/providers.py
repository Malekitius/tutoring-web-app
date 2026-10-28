"""Provider boundary. Other vendors implement TextProvider; workflows stay unchanged."""

import base64
import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .https import verified_context


class ProviderError(Exception):
    pass


class TextProvider(Protocol):
    def complete(self, instructions: str, prompt: str, *, json_mode: bool = False,
                 files: list[tuple[str, bytes]] | None = None) -> str: ...


def user_content(prompt, files):
    if not files:
        return prompt
    content = [{"type": "input_text", "text": prompt}]
    for name, data in files:
        content.append({"type": "input_file", "filename": name,
                        "file_data": "data:application/pdf;base64," + base64.b64encode(data).decode("ascii")})
    return content


@dataclass
class OpenAIResponsesProvider:
    api_key: str
    model: str

    def complete(self, instructions: str, prompt: str, *, json_mode: bool = False,
                 files: list[tuple[str, bytes]] | None = None) -> str:
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": [{"role": "user", "content": user_content(prompt, files)}],
            "store": False,
        }
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=90, context=verified_context()) as response:
                data = json.load(response)
        except HTTPError as exc:
            if exc.code == 401:
                raise ProviderError("Ключ модели не принят. Проверьте TUTOR_ASSISTANT_API_KEY.") from exc
            if exc.code == 429:
                raise ProviderError("Достигнут лимит запросов модели. Попробуйте позже.") from exc
            raise ProviderError(f"Сервис модели вернул ошибку {exc.code}.") from exc
        except (URLError, TimeoutError) as exc:
            raise ProviderError("Не удалось связаться с сервисом модели.") from exc
        chunks = [part.get("text", "") for item in data.get("output", [])
                  if item.get("type") == "message" for part in item.get("content", [])
                  if part.get("type") == "output_text"]
        result = "".join(chunks).strip()
        if not result:
            raise ProviderError("Модель не вернула текстовый ответ.")
        return result


class ChatGPTPlanProvider:
    """The same workflow via the user's authorized ChatGPT plan."""

    def complete(self, instructions: str, prompt: str, *, json_mode: bool = False,
                 files: list[tuple[str, bytes]] | None = None) -> str:
        from .chatgpt_auth import credentials

        account = credentials()
        if not account or not account.get("model"):
            raise ProviderError("Подключите аккаунт ChatGPT заново.")
        payload = {
            "model": account["model"],
            "instructions": instructions,
            "input": [{"role": "user", "content": user_content(prompt, files)}],
            "store": False,
            "stream": True,
        }
        # The preview route has a narrower request contract; JSON is requested in the prompt.
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {account['access_token']}", "Content-Type": "application/json"},
            method="POST",
        )
        chunks = []
        completed = False
        try:
            with urlopen(request, timeout=90, context=verified_context()) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    if event.get("type") == "response.output_text.delta":
                        chunks.append(event.get("delta", ""))
                    elif event.get("type") == "response.completed":
                        completed = True
                        if not chunks:
                            for item in event.get("response", {}).get("output", []):
                                for part in item.get("content", []):
                                    if part.get("type") == "output_text":
                                        chunks.append(part.get("text", ""))
                    elif event.get("type") in {"response.failed", "response.incomplete"}:
                        code = (event.get("response", {}).get("error") or {}).get("code")
                        if code == "subscription_sharing_usage_limit_exceeded":
                            raise ProviderError("Достигнут лимит подписки ChatGPT. Проверьте использование в настройках ChatGPT.")
                        raise ProviderError("Запрос к модели не завершился. Попробуйте ещё раз.")
        except HTTPError as exc:
            if exc.code == 401:
                raise ProviderError("Сессия ChatGPT недействительна. Подключите аккаунт заново.") from exc
            if exc.code == 429:
                raise ProviderError("Достигнут лимит подписки ChatGPT. Попробуйте позже.") from exc
            raise ProviderError(f"Сервис модели вернул ошибку {exc.code}.") from exc
        except (URLError, TimeoutError) as exc:
            raise ProviderError("Не удалось связаться с сервисом модели.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Сервис модели вернул некорректный поток ответа.") from exc
        if not completed:
            raise ProviderError("Соединение с моделью прервалось до завершения ответа.")
        result = "".join(chunks).strip()
        if not result:
            raise ProviderError("Модель не вернула текстовый ответ.")
        return result


def get_provider() -> TextProvider:
    name = os.environ.get("TUTOR_ASSISTANT_PROVIDER", "auto")
    if name not in {"auto", "openai", "openai_plan"}:
        raise ProviderError(f"Поставщик модели «{name}» пока не подключён.")
    if name in {"auto", "openai_plan"}:
        from .chatgpt_auth import credentials

        account = credentials()
        if account and account.get("model"):
            return ChatGPTPlanProvider()
        if name == "openai_plan":
            raise ProviderError("Подключите аккаунт ChatGPT через плавающую кнопку помощника.")
    api_key = os.environ.get("TUTOR_ASSISTANT_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("Подключите ChatGPT или задайте TUTOR_ASSISTANT_API_KEY для сервера.")
    return OpenAIResponsesProvider(api_key, os.environ.get("TUTOR_ASSISTANT_MODEL", "gpt-6.1-sol"))
