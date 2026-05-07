"""
OpenAI / OpenAI-compatible cloud LLM client.
Wraps the OpenAI Chat Completions API (and any OpenAI-compatible provider)
into the same {"response": "..."} envelope expected by the SentimentEngine.

Supports:
  - JSON Schema via response_format (OpenAI structured outputs)
  - force_json via response_format: {"type": "json_object"}
  - Private IP address detection for local servers (allows HTTP for LAN, requires HTTPS for public)
  - Thread-safe (stateless, no shared mutable state)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests


def _is_private_url(url: str) -> bool:
    """Check if a URL resolves to a private/reserved IP address range."""
    import ipaddress
    import socket
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    _PRIVATE_NETWORKS = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]
    try:
        addr = socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            for net in _PRIVATE_NETWORKS:
                if ip in net:
                    return True
    except Exception:
        return True  # conservative: block if resolution fails
    return False


def _validate_base_url(base_url: str) -> str:
    """Validate and normalize the base URL for an OpenAI-compatible API.

    - Must be http:// (private IPs only) or https:// (all)
    - Must not point to a private IP when using http://
    - Trailing /v1/completions, /v1/chat/completions are stripped
    """
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("OpenAI base URL is required")

    # Strip common path suffixes so the user can paste the full endpoint
    for suffix in ("/v1/chat/completions", "/v1/completions", "/v1", "/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    url = url.rstrip("/")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"OpenAI base URL must use http or https, got '{scheme}'")

    is_private = _is_private_url(url)
    if scheme == "http" and not is_private:
        raise ValueError(
            "http:// is only allowed for local/private endpoints "
            "(e.g. http://localhost:8080, http://192.168.1.50:8000). "
            "Use https:// for public cloud providers."
        )

    return url


def call_openai_chat_sync(
    prompt: str,
    model: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    force_json: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    max_tokens: int = 2048,
    temperature: float = 0.10,
    timeout: int = 180,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible chat completions API and return the response.

    Returns the same ``{"response": "..."}`` envelope as Ollama's ``/api/generate``
    so that the existing ``_extract_json_value`` / ``_sanitize_json`` / ``_parse_response``
    pipeline works unchanged.

    Args:
        prompt: The raw prompt string (converted to chat messages internally).
        model: The model name (e.g. "gpt-4o-mini", "gpt-4o", "accounts/fireworks/models/...").
        api_key: Bearer token for the API.
        base_url: Root URL of the API (e.g. "https://api.openai.com/v1").
        force_json: If True, sets response_format to {"type": "json_object"}.
        response_schema: A JSON Schema dict. If provided, sets response_format to
            {"type": "json_schema", "json_schema": {"schema": ..., "name": "response"}}.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.
        timeout: HTTP request timeout in seconds.

    Returns:
        {"response": "<text>"}
    """
    base_url = _validate_base_url(base_url)

    api_url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Convert the raw prompt string into a chat messages array.
    # The existing system sends a single prompt string that contains both
    # system-level instructions and the user input. We split on a heuristic:
    # if the prompt starts with a known system-style instruction pattern, we
    # put the first paragraph as system and the rest as user.
    # Otherwise, we wrap the whole thing as a user message.
    messages = _build_chat_messages(prompt)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # Map response schema / force_json to OpenAI's response_format
    if response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_response",
                "strict": True,
                "schema": response_schema,
            },
        }
    elif force_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    session = requests.Session()
    start_time = time.time()

    print(f"OpenAI [{model}] → {api_url} (force_json={force_json}, max_tokens={max_tokens})")

    try:
        response = session.post(api_url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        latency = (time.time() - start_time) * 1000

        # Extract the text from the OpenAI response format
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenAI API returned empty choices array")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        print(f"OpenAI [{model}] completed in {latency:.1f}ms (input={data.get('usage', {}).get('prompt_tokens', '?')}t output={data.get('usage', {}).get('completion_tokens', '?')}t)")

        # Return in the same envelope as Ollama's /api/generate
        return {"response": content}

    except requests.exceptions.Timeout:
        raise Exception("OpenAI API timeout")
    except requests.exceptions.ConnectionError:
        raise Exception("Cannot connect to OpenAI API. Is the base URL correct?")
    except requests.exceptions.HTTPError as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        body_text = ""
        if e.response is not None:
            try:
                body_payload = e.response.json()
                body_text = str(body_payload.get("error", {}).get("message", "") or body_payload)
            except Exception:
                body_text = str(getattr(e.response, "text", "") or "")
        detail = body_text.strip() or str(e)
        if status_code == 401:
            raise Exception(
                f"OpenAI API authentication failed. "
                f"URL: {api_url}, Model: {model}. "
                f"Check your API key and base URL in the admin LLM Configuration section."
            )
        if status_code == 404:
            raise Exception(f"OpenAI model not found: `{model}`. Verify the model name and base URL.")
        raise Exception(f"OpenAI API HTTP {status_code}: {detail}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON response from OpenAI: {e}")
    except Exception as e:
        raise Exception(f"OpenAI API error: {e}")


def _build_chat_messages(prompt: str) -> List[Dict[str, str]]:
    """Split a raw prompt string into system + user chat messages.

    Heuristic: if the prompt starts with a capitalized instruction sentence
    (e.g. "You are a financial analyst..." or "Analyze the following text...")
    we treat the first paragraph as the system instruction and the rest as user input.
    Otherwise, the entire prompt is sent as a user message.
    """
    text = str(prompt or "").strip()
    if not text:
        return [{"role": "user", "content": "Hello."}]

    # Split on double newline to separate system context from user input
    paragraphs = re.split(r"\n\n+", text, maxsplit=1)

    if len(paragraphs) >= 2:
        first = paragraphs[0].strip()
        rest = paragraphs[1].strip()
        # If the first paragraph looks like an instruction (starts with "You are",
        # "Analyze", "Given", "As an", etc.), treat it as system message
        if re.match(
            r"^(You are|Analyze|Given|As an|Your task|Your role|You handle|For each|The following)",
            first,
            re.IGNORECASE,
        ):
            return [
                {"role": "system", "content": first},
                {"role": "user", "content": rest},
            ]

    # Single paragraph or no clear split: use entire prompt as user message
    return [{"role": "user", "content": text}]


def get_openai_status(
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    timeout: int = 3,
) -> Dict[str, Any]:
    """Check reachability and list available models from an OpenAI-compatible API.

    Returns the same shape as ``get_ollama_status()`` so the status endpoint
    can be generic.
    """
    base_url = _validate_base_url(base_url)
    models_url = f"{base_url.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(models_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        available_models: List[str] = []
        for model in data.get("data", []):
            model_id = str(model.get("id", "") or "").strip()
            if model_id:
                available_models.append(model_id)
        available_models.sort()

        # ── Verify actual inference capability ──────────────────────────
        # Listing models only requires a read-only key; chat completions
        # require a write-capable key. Test with a minimal prompt to confirm
        # the key can actually do inference (the operation that matters).
        inference_ok = False
        inference_error = ""
        chat_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        try:
            chat_resp = requests.post(
                chat_url,
                json={
                    "model": available_models[0] if available_models else "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                },
                headers=headers,
                timeout=timeout,
            )
            if chat_resp.status_code == 200:
                inference_ok = True
            elif chat_resp.status_code == 401:
                inference_error = "Authentication failed — API key may be read-only or invalid for chat completions. Check your API key."
            elif chat_resp.status_code == 404:
                inference_error = f"Model not found for inference. Verify the model name."
            else:
                try:
                    err_body = chat_resp.json()
                    inference_error = str(err_body.get("error", {}).get("message", chat_resp.text[:200]))
                except Exception:
                    inference_error = chat_resp.text[:200]
        except Exception as exc:
            inference_error = str(exc)[:200]

        return {
            "reachable": True,
            "openai_root": base_url,
            "configured_model": os.getenv("OPENAI_MODEL", "").strip(),
            "active_model": available_models[0] if available_models else "",
            "available_models": available_models,
            "running_models": [],
            "resolution": "connected" if available_models else "no_models",
            "api_key_configured": bool(api_key),
            "inference_tested": inference_ok,
            "inference_error": inference_error,
        }
    except requests.exceptions.Timeout:
        return {
            "reachable": False,
            "openai_root": base_url,
            "configured_model": os.getenv("OPENAI_MODEL", "").strip(),
            "active_model": "",
            "available_models": [],
            "running_models": [],
            "resolution": "unreachable",
            "api_key_configured": bool(api_key),
            "error": "Connection timed out",
        }
    except requests.exceptions.ConnectionError:
        return {
            "reachable": False,
            "openai_root": base_url,
            "configured_model": os.getenv("OPENAI_MODEL", "").strip(),
            "active_model": "",
            "available_models": [],
            "running_models": [],
            "resolution": "unreachable",
            "api_key_configured": bool(api_key),
            "error": "Cannot connect",
        }
    except requests.exceptions.HTTPError as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        error_text = ""
        if e.response is not None:
            try:
                error_text = str(e.response.json().get("error", {}).get("message", str(e.response.json())))
            except Exception:
                error_text = str(getattr(e.response, "text", "") or str(e))
        return {
            "reachable": False,
            "openai_root": base_url,
            "configured_model": os.getenv("OPENAI_MODEL", "").strip(),
            "active_model": "",
            "available_models": [],
            "running_models": [],
            "resolution": f"error_{status_code}",
            "api_key_configured": bool(api_key),
            "error": error_text,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "openai_root": base_url,
            "configured_model": os.getenv("OPENAI_MODEL", "").strip(),
            "active_model": "",
            "available_models": [],
            "running_models": [],
            "resolution": "unreachable",
            "api_key_configured": bool(api_key),
            "error": str(exc),
        }