from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env", override=False)


class AgentNotConfigured(ValueError):
    """Required LLM/database settings are missing."""


@dataclass(frozen=True)
class AgentSettings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    database_url: str
    pdf_render_cache_dir: Path
    pdf_render_dpi: int
    llm_prompt_cache_key: str = ""  # optional; sent only when set, for gateways that route by prompt_cache_key

    @classmethod
    def from_env(cls) -> "AgentSettings":
        cache_dir = Path(os.getenv("PDF_RENDER_CACHE_DIR", "data/render_cache"))
        if not cache_dir.is_absolute():
            cache_dir = BACKEND_ROOT / cache_dir
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            database_url=os.getenv("RAG_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip(),
            pdf_render_cache_dir=cache_dir,
            pdf_render_dpi=int(os.getenv("PDF_RENDER_DPI", "150")),
            llm_prompt_cache_key=os.getenv("LLM_PROMPT_CACHE_KEY", "").strip(),
        )

    def validate_llm(self) -> None:
        if not self.llm_base_url or not self.llm_api_key or not self.llm_model:
            raise AgentNotConfigured("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be configured in backend/.env")
        if not self.database_url:
            raise AgentNotConfigured("RAG_DATABASE_URL or DATABASE_URL must be configured in backend/.env")
