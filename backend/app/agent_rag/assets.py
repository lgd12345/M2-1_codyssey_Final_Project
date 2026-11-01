from __future__ import annotations

from dataclasses import dataclass
import re
from secrets import token_urlsafe

from markdown_it import MarkdownIt


class AssetReferenceError(ValueError):
    """The answer references an image that this agent run did not open."""


@dataclass(frozen=True)
class SourceAsset:
    asset_id: str
    data: bytes
    document_sha256: str
    pdf_page: int
    media_type: str = "image/png"


_MARKDOWN = MarkdownIt("commonmark", {"html": True})
_ASSET = re.compile(r"^asset:([A-Za-z0-9_-]+)$")


class AssetRegistry:
    """Per-run allowlist for rendered source-page images."""

    def __init__(self) -> None:
        self._assets: dict[str, SourceAsset] = {}

    def register(self, data: bytes, *, document_sha256: str, pdf_page: int,
                 media_type: str = "image/png") -> str:
        if not data:
            raise ValueError("asset image cannot be empty")
        if pdf_page < 1:
            raise ValueError("pdf_page must be positive")
        asset_id = token_urlsafe(18)
        self._assets[asset_id] = SourceAsset(asset_id, data, document_sha256, pdf_page, media_type)
        return asset_id

    def get(self, asset_id: str) -> SourceAsset:
        try:
            return self._assets[asset_id]
        except KeyError as exc:
            raise AssetReferenceError("image asset was not opened in this agent run") from exc

    def all(self) -> tuple[SourceAsset, ...]:
        return tuple(self._assets.values())

    def validate_markdown(self, markdown: str) -> str:
        """Validate parsed CommonMark, not literal examples inside code blocks/spans.

        Raw HTML is unsupported. Reference-style images are resolved by the parser
        and checked against the same asset allowlist as inline images.
        """
        def validate_tokens(tokens):
            for token in tokens:
                if token.type in {"html_inline", "html_block"}:
                    raise AssetReferenceError("raw HTML is not allowed; use an opened source asset")
                if token.type == "image":
                    target = token.attrGet("src") or ""
                    asset = _ASSET.fullmatch(target)
                    if not asset:
                        raise AssetReferenceError("image output must reference an opened source asset")
                    self.get(asset.group(1))
                if token.type == "text":
                    for asset_id in re.findall(r"asset:([A-Za-z0-9_-]+)", token.content):
                        self.get(asset_id)
                if token.children:
                    validate_tokens(token.children)

        validate_tokens(_MARKDOWN.parse(markdown))
        return markdown
