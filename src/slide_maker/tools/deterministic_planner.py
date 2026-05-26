from __future__ import annotations

import re

from slide_maker.errors import InputValidationError
from slide_maker.models import Chapter, ExampleQuestion, Slide, SlideDeck

MARKDOWN_IMAGE_LINE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def plan_deck(chapter: Chapter, slide_count: int, question_count: int) -> SlideDeck:
    if slide_count < 1:
        raise InputValidationError("slide_count must be at least 1.")
    if question_count < 0:
        raise InputValidationError("question_count cannot be negative.")

    paragraphs = _content_blocks(chapter.text)
    if not paragraphs:
        raise InputValidationError("No usable chapter content found.")

    rendered_question_count = min(question_count, slide_count)
    content_slide_count = slide_count - rendered_question_count
    content_chunks = (
        _chunk_evenly(paragraphs, content_slide_count) if content_slide_count else []
    )
    question_chunks = _chunk_evenly(paragraphs, question_count) if question_count else []
    questions = tuple(
        _question_from_chunk(idx, chunk)
        for idx, chunk in enumerate(question_chunks, start=1)
    )
    content_slides = tuple(
        _slide_from_chunk(chapter.title, idx, chunk)
        for idx, chunk in enumerate(content_chunks, start=1)
    )
    question_slides = tuple(
        _question_slide(idx, question)
        for idx, question in enumerate(questions[:rendered_question_count], start=1)
    )
    slides = content_slides + question_slides
    return SlideDeck(
        title=chapter.title,
        slides=slides,
        questions=questions,
        used_llm=False,
    )


def _content_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for raw in re.split(r"\n\s*\n", text):
        clean = MARKDOWN_IMAGE_LINE.sub("", raw).strip()
        clean = re.sub(r"^#+\s*", "", clean)
        clean = _plain_slide_text(clean)
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            blocks.append(clean)
    return blocks


def _chunk_evenly(items: list[str], count: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    for idx in range(count):
        start = round(idx * len(items) / count)
        end = round((idx + 1) * len(items) / count)
        chunk = items[start:end] or [items[min(idx, len(items) - 1)]]
        chunks.append(chunk)
    return chunks


def _slide_from_chunk(deck_title: str, index: int, chunk: list[str]) -> Slide:
    heading = _short_title(chunk[0], fallback=f"{deck_title}: Part {index}")
    bullets = tuple(_bulletize(" ".join(chunk))[:4])
    notes = " ".join(chunk)
    return Slide(title=heading, bullets=bullets, speaker_notes=notes)


def _short_title(text: str, fallback: str) -> str:
    sentence = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
    words = sentence.split()
    if not words:
        return fallback
    return " ".join(words[:9])


def _bulletize(text: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) < 2:
        words = text.split()
        sentences = [" ".join(words[i:i + 18]) for i in range(0, len(words), 18)]
    return [_fit_bullet(sentence) for sentence in sentences if sentence]


def _fit_bullet(text: str, limit: int = 120) -> str:
    clean = _plain_slide_text(text).strip(" -")
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rsplit(" ", 1)[0] + "."


def _question_from_chunk(index: int, chunk: list[str]) -> ExampleQuestion:
    topic = _short_title(chunk[0], fallback=f"topic {index}").lower()
    answer = _fit_bullet(" ".join(chunk), limit=180)
    return ExampleQuestion(
        prompt=f"How would you explain {topic} in your own words?",
        answer=answer,
    )


def _question_slide(index: int, question: ExampleQuestion) -> Slide:
    return Slide(
        title=f"Question {index}",
        bullets=(question.prompt, f"Answer: {question.answer}"),
        speaker_notes=question.answer,
    )


def _plain_slide_text(text: str) -> str:
    clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"[*_`~]+", "", clean)
    clean = re.sub(r"^\s*(?:[-*+]|\d+[.)]|\u2022)\s+", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
