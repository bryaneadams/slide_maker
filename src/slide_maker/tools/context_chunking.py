from __future__ import annotations

from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class ChunkedContext:
    chunks: tuple[str, ...]
    estimated_tokens: int
    max_tokens: int

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def text(self) -> str:
        if not self.chunks:
            return ""
        rendered = []
        for idx, chunk in enumerate(self.chunks, start=1):
            rendered.append(f"=== Chapter Chunk {idx}/{len(self.chunks)} ===\n{chunk.strip()}")
        return "\n\n".join(rendered)


def chunk_text_for_llm(
    text: str,
    max_tokens: int = 6000,
    target_chunk_tokens: int | None = None,
) -> ChunkedContext:
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")

    paragraphs = _paragraphs(text)
    if not paragraphs:
        return ChunkedContext(chunks=(), estimated_tokens=0, max_tokens=max_tokens)

    target = target_chunk_tokens or max(500, max_tokens // 3)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    estimated_total_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = _estimate_tokens(paragraph)
        estimated_total_tokens += paragraph_tokens
        if current and current_tokens + paragraph_tokens > target:
            chunks.append("\n\n".join(current).strip())
            current = [paragraph]
            current_tokens = paragraph_tokens
        else:
            current.append(paragraph)
            current_tokens += paragraph_tokens

    if current:
        chunks.append("\n\n".join(current).strip())

    if estimated_total_tokens <= max_tokens:
        return ChunkedContext(tuple(chunks), estimated_total_tokens, max_tokens)

    compressed: list[str] = []
    running_tokens = 0
    for chunk in chunks:
        chunk_tokens = _estimate_tokens(chunk)
        if compressed and running_tokens + chunk_tokens > max_tokens:
            break
        compressed.append(chunk)
        running_tokens += chunk_tokens

    if not compressed:
        compressed = [chunks[0]]
        running_tokens = _estimate_tokens(chunks[0])

    return ChunkedContext(tuple(compressed), estimated_total_tokens, max_tokens)


def _paragraphs(text: str) -> list[str]:
    cleaned = re.sub(r"\r\n?", "\n", text).strip()
    if not cleaned:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))
