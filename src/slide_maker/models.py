from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BookImage:
    path: Path
    alt_text: str = ""
    source: str = ""


@dataclass(frozen=True)
class Chapter:
    title: str
    text: str
    images: tuple[BookImage, ...] = ()


@dataclass(frozen=True)
class ChapterAnalysis:
    summary: str
    key_concepts: tuple[str, ...] = ()
    key_terms: tuple[str, ...] = ()
    example_questions: tuple[str, ...] = ()
    cautions: tuple[str, ...] = ()
    used_llm: bool = False


@dataclass(frozen=True)
class ExampleQuestion:
    prompt: str
    answer: str


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: tuple[str, ...]
    speaker_notes: str = ""
    image_path: Path | None = None


@dataclass(frozen=True)
class SlideDeck:
    title: str
    slides: tuple[Slide, ...]
    questions: tuple[ExampleQuestion, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)
    used_llm: bool = False


@dataclass(frozen=True)
class WorkflowResult:
    output_path: Path
    deck: SlideDeck
    warnings: tuple[str, ...] = ()
