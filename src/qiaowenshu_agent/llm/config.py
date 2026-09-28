"""Configuration and model routing for OpenAI-compatible Qwen endpoints."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class LLMConfigurationError(ValueError):
    """Raised when the LLM configuration is present but unusable."""


# The defaults intentionally distinguish extraction, long-context reading and
# high-stakes drafting. Every value can be replaced per purpose through env.
DEFAULT_MODEL_ROUTES: dict[str, str] = {
    "ocr": "qwen-vl-ocr",
    "document_profile": "qwen3.7-flash",
    "tender_intake": "qwen-long",
    "tender_decomposition": "qwen3.7-plus",
    "bid_rejection_check": "qwen3.8-max",
    "scoring_strategy": "qwen3.8-max",
    "document_writing": "qwen3.8-max",
    "technical_response": "qwen3.8-max",
    "commercial_response": "qwen3.7-plus",
    "compliance_review": "qwen3.8-max",
    "tender_interpret": "qwen3.7-plus",
    "evidence_matching": "rule",
    "bid_feasibility": "rule",
}


@dataclass(frozen=True)
class QwenConfig:
    """Runtime settings for an OpenAI-compatible Qwen service.

    ``base_url`` should normally be the provider's versioned API root, for
    example ``https://host/api/v1``. The client appends ``/chat/completions``.
    ``api_key`` is excluded from repr so configuration cannot accidentally be
    printed into logs or test output.
    """

    base_url: str
    api_key: str | None = field(default=None, repr=False)
    default_model: str = "qwen3.7-plus"
    model_routes: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_ROUTES)
    )
    available_models: tuple[str, ...] = ()
    timeout_seconds: float = 180.0
    max_retries: int = 2
    temperature: float = 0.2
    max_tokens: int = 4096
    dotenv_path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise LLMConfigurationError("LLM base_url is required")
        if self.timeout_seconds <= 0:
            raise LLMConfigurationError("LLM timeout_seconds must be positive")
        if self.max_retries < 0:
            raise LLMConfigurationError("LLM max_retries cannot be negative")
        if self.max_tokens <= 0:
            raise LLMConfigurationError("LLM max_tokens must be positive")
        if not 0 <= self.temperature <= 2:
            raise LLMConfigurationError("LLM temperature must be between 0 and 2")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        dotenv_path: str | Path | None = None,
    ) -> "QwenConfig | None":
        """Load settings from process env and an optional local ``.env``.

        Explicit ``environ`` is treated as a complete test/config mapping and
        therefore does not read a local file. For normal application startup,
        values in the process environment take precedence over ``.env``.
        """

        if environ is not None:
            env = dict(environ)
            loaded_dotenv: str | None = None
        else:
            path = Path(dotenv_path or os.getenv("QIAOWENSHU_ENV_FILE", ".env"))
            env = _read_dotenv(path) if path.is_file() else {}
            env.update(os.environ)
            loaded_dotenv = str(path) if path.is_file() else None

        base_url = _first_env(
            env,
            "QIAOWENSHU_LLM_API_BASE_URL",
            "LLM_API_BASE_URL",
        )
        if not base_url:
            return None

        routes = dict(DEFAULT_MODEL_ROUTES)
        for purpose in routes:
            env_name = _route_env_name(purpose)
            configured = _first_env(
                env,
                env_name,
                *_legacy_route_env_names(purpose),
            )
            if configured:
                routes[purpose] = configured

        raw_route_map = _first_env(
            env,
            "QIAOWENSHU_LLM_MODEL_ROUTES",
            "LLM_MODEL_ROUTES",
        )
        if raw_route_map:
            try:
                decoded = json.loads(raw_route_map)
            except json.JSONDecodeError as exc:
                raise LLMConfigurationError(
                    "QIAOWENSHU_LLM_MODEL_ROUTES must be valid JSON"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise LLMConfigurationError(
                    "QIAOWENSHU_LLM_MODEL_ROUTES must be a JSON object"
                )
            for purpose, model in decoded.items():
                purpose_name = str(purpose).strip().replace("-", "_")
                model_name = str(model).strip()
                if purpose_name and model_name:
                    routes[purpose_name] = model_name

        default_model = (
            _first_env(
                env,
                "QIAOWENSHU_LLM_DEFAULT_MODEL",
                "LLM_MODEL",
            )
            or "qwen3.7-plus"
        )
        available_models = _parse_csv(
            _first_env(
                env,
                "QIAOWENSHU_LLM_AVAILABLE_MODELS",
                "LLM_AVAILABLE_MODELS",
            )
        )
        return cls(
            base_url=base_url,
            api_key=_first_env(
                env,
                "QIAOWENSHU_LLM_API_KEY",
                "LLM_API_KEY",
            ),
            default_model=default_model,
            model_routes=routes,
            available_models=available_models,
            timeout_seconds=_parse_float(
                _first_env(
                    env,
                    "QIAOWENSHU_LLM_TIMEOUT_SECONDS",
                    "LLM_TIMEOUT_SECONDS",
                ),
                default=180.0,
            ),
            max_retries=_parse_int(
                _first_env(
                    env,
                    "QIAOWENSHU_LLM_MAX_RETRIES",
                    "LLM_MAX_RETRIES",
                ),
                default=2,
            ),
            temperature=_parse_float(
                _first_env(
                    env,
                    "QIAOWENSHU_LLM_TEMPERATURE",
                    "LLM_TEMPERATURE",
                ),
                default=0.2,
            ),
            max_tokens=_parse_int(
                _first_env(
                    env,
                    "QIAOWENSHU_LLM_MAX_TOKENS",
                    "LLM_MAX_TOKENS",
                ),
                default=4096,
            ),
            dotenv_path=loaded_dotenv,
        )

    def model_for(self, purpose: str, override: str | None = None) -> str:
        """Return a configured model for a Skill purpose."""

        requested = str(override or "").strip()
        if requested:
            return requested
        normalized = str(purpose).strip().replace("-", "_")
        return str(self.model_routes.get(normalized) or self.default_model)

    def public_dict(self) -> dict[str, Any]:
        """Return safe diagnostics without exposing the API key."""

        return {
            "base_url": self.base_url,
            "configured": True,
            "api_key_configured": bool(self.api_key),
            "default_model": self.default_model,
            "model_routes": dict(self.model_routes),
            "available_models": list(self.available_models),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


def _route_env_name(purpose: str) -> str:
    return f"QIAOWENSHU_LLM_MODEL_{purpose.upper()}"


def _legacy_route_env_names(purpose: str) -> tuple[str, ...]:
    aliases = {
        "ocr": ("LLM_OCR_MODEL",),
        "tender_intake": ("LLM_STRUCTURED_EXTRACT_MODEL",),
        "tender_interpret": ("LLM_TENDER_INTERPRET_MODEL",),
        "bid_rejection_check": ("LLM_BID_REJECTION_CHECK_MODEL",),
        "document_writing": ("LLM_BID_INTELLIGENT_WRITE_MODEL",),
    }
    return aliases.get(purpose, ())


def _first_env(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return None


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_float(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"invalid float configuration: {value}") from exc


def _parse_int(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"invalid integer configuration: {value}") from exc


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read the small KEY=VALUE subset needed by this project."""

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        name = name.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if name:
            values[name] = value
    return values
