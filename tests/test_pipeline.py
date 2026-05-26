from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from slide_maker.config import OrchestrationConfig, SlideMakerConfig, load_config
from slide_maker.crews.slide_deck_crew.slide_deck_crew import (
    _crewai_model_name,
    _deck_from_json,
)
from slide_maker.errors import InputValidationError
from slide_maker.main import SlideMakerFlow, SlideMakerState, run
from slide_maker.models import BookImage, Chapter
from slide_maker.crews.slide_deck_crew import SlideDeckCrew
from slide_maker.tools.chapter_ingest import load_chapter
from slide_maker.tools.context_chunking import chunk_text_for_llm
from slide_maker.tools.deterministic_planner import plan_deck
from slide_maker.tools.image_assignment import attach_images
from slide_maker.tools.pptx_writer import write_pptx


def test_load_chapter_extracts_title_and_markdown_images(tmp_path):
    image = tmp_path / "chloroplast.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    chapter = tmp_path / "chapter.md"
    chapter.write_text(
        "# Plant Energy\n\n![chloroplast diagram](chloroplast.png)\n\nPlants capture light.",
        encoding="utf-8",
    )

    result = load_chapter(chapter)

    assert result.title == "Plant Energy"
    assert result.images == (
        BookImage(
            path=image.resolve(), alt_text="chloroplast diagram", source="markdown"
        ),
    )


def test_load_chapter_extracts_text_from_pdf(tmp_path):
    chapter = tmp_path / "chapter.pdf"
    _write_minimal_pdf(
        chapter, ["Photosynthesis Chapter", "Plants capture light energy."]
    )

    result = load_chapter(chapter)

    assert result.title == "Photosynthesis Chapter"
    assert "Plants capture light energy." in result.text


def test_plan_deck_creates_requested_slides_and_questions():
    chapter = Chapter(
        title="Energy",
        text="Energy moves through systems.\n\nPlants capture light.\n\nConsumers use stored chemical energy.",
    )

    deck = plan_deck(chapter, slide_count=3, question_count=2)

    assert len(deck.slides) == 3
    assert len(deck.questions) == 2
    assert all(slide.bullets for slide in deck.slides)


def test_plan_deck_puts_questions_on_final_slides():
    chapter = Chapter(
        title="Energy",
        text=(
            "Energy moves through systems.\n\n"
            "Plants capture light.\n\n"
            "Consumers use stored chemical energy.\n\n"
            "Food webs show energy transfer."
        ),
    )

    deck = plan_deck(chapter, slide_count=5, question_count=3)

    assert [slide.title for slide in deck.slides[-3:]] == [
        "Question 1",
        "Question 2",
        "Question 3",
    ]
    assert all(slide.bullets[0].endswith("?") for slide in deck.slides[-3:])


def test_crewai_deck_json_is_plain_text_and_reserves_question_slides():
    raw = """
    {
      "title": "**Energy**",
      "slides": [
        {"title": "**Overview**", "bullets": ["* Systems move energy"], "speaker_notes": "__Teach this__"},
        {"title": "Extra", "bullets": ["Should be replaced"], "speaker_notes": ""}
      ],
      "questions": [
        {"prompt": "**What changes form?**", "answer": "* Energy"}
      ]
    }
    """

    deck = _deck_from_json(raw, "Fallback", slide_count=2, question_count=1)

    assert deck.title == "Energy"
    assert deck.slides[0].title == "Overview"
    assert deck.slides[0].bullets == ("Systems move energy",)
    assert deck.slides[-1].title == "Question 1"
    assert deck.slides[-1].bullets == ("What changes form?", "Answer: Energy")


def test_load_config_reads_api_keys_from_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=local-test-key\n", encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(
        """
        {
          "default_llm": "openai_fast",
          "env_file": ".env",
          "llms": {
            "openai_fast": {
              "provider": "openai",
              "model": "gpt-4o-mini",
              "api_key_env": "OPENAI_API_KEY"
            }
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.api_key_for() == "local-test-key"


def test_crewai_model_names_support_gemini_and_groq():
    assert _crewai_model_name("gemini", "gemini-2.0-flash") == "google/gemini-2.0-flash"
    assert _crewai_model_name("google", "gemini-2.0-flash") == "google/gemini-2.0-flash"
    assert (
        _crewai_model_name("groq", "llama-3.1-70b-versatile")
        == "groq/llama-3.1-70b-versatile"
    )


def test_crew_steps_can_be_run_individually():
    config = SlideMakerConfig(orchestration=OrchestrationConfig(mode="deterministic"))
    crew = SlideDeckCrew(config)
    chapter = Chapter(
        title="Energy",
        text="Energy moves through systems.\n\nPlants capture light.\n\nConsumers use stored chemical energy.",
    )

    analysis = crew.analyze_chapter(chapter)
    deck = crew.create_slide_deck(chapter, analysis, slide_count=3, question_count=2)

    assert analysis.summary
    assert len(analysis.key_concepts) >= 1
    assert analysis.used_llm is False
    assert len(deck.slides) == 3
    assert len(deck.questions) == 2
    assert deck.used_llm is False


def test_flow_exposes_analysis_and_deck_steps(tmp_path):
    chapter_path = tmp_path / "chapter.md"
    chapter_path.write_text(
        "# Energy\n\nPlants capture light.\n\nConsumers use stored energy.",
        encoding="utf-8",
    )
    state = SlideMakerState(
        chapter_path=str(chapter_path),
        output_path=str(tmp_path / "deck.pptx"),
        slide_count=3,
        question_count=1,
    )
    flow = SlideMakerFlow(**state.model_dump())

    chapter = flow.ingest_chapter()
    analysis = flow.analyze_chapter(chapter)
    deck = flow.create_slide_deck(analysis)

    assert flow.state.chapter == chapter
    assert flow.state.analysis == analysis
    assert flow.state.deck == deck
    assert len(deck.slides) == 3


def test_chunk_text_for_llm_limits_context_size():
    text = "\n\n".join(f"Paragraph {index} " + ("x" * 3000) for index in range(1, 8))
    chunked = chunk_text_for_llm(text, max_tokens=2000)

    assert chunked.chunk_count >= 1
    assert chunked.estimated_tokens > 2000
    assert chunked.text.startswith("=== Chapter Chunk 1/")


def test_plan_deck_validates_counts():
    with pytest.raises(InputValidationError):
        plan_deck(Chapter(title="Bad", text="Content"), slide_count=0, question_count=1)


def test_attach_images_assigns_book_images(tmp_path):
    image = tmp_path / "light_reactions.png"
    image.write_bytes(b"fake")
    deck = plan_deck(Chapter(title="Light", text="Light reactions produce ATP."), 1, 0)

    result = attach_images(deck, (BookImage(path=image, alt_text="light reactions"),))

    assert result.slides[0].image_path == image


def test_write_pptx_outputs_valid_zip_package(tmp_path):
    deck = plan_deck(
        Chapter(title="Energy", text="Plants capture light.\n\nConsumers use energy."),
        2,
        1,
    )
    output = tmp_path / "deck.pptx"

    write_pptx(deck, output)

    assert output.exists()
    with zipfile.ZipFile(output) as pptx:
        names = set(pptx.namelist())
    assert "ppt/presentation.xml" in names
    assert "ppt/slides/slide1.xml" in names
    assert "ppt/slides/slide2.xml" in names


def test_workflow_runs_end_to_end_without_live_llm(tmp_path):
    chapter = tmp_path / "chapter.pdf"
    _write_minimal_pdf(
        chapter, ["Energy", "Plants capture light.", "Consumers use energy."]
    )
    output = tmp_path / "deck.pptx"

    result = run(chapter, output, slide_count=2, question_count=1)

    assert result.output_path == output
    assert len(result.deck.slides) == 2
    assert output.exists()


def _write_minimal_pdf(path: Path, lines: list[str]) -> None:
    text_commands = ["BT /F1 24 Tf 72 720 Td"]
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index == 0:
            text_commands.append(f"({escaped}) Tj")
        else:
            text_commands.append(f"0 -40 Td ({escaped}) Tj")
    text_commands.append("ET")
    content = " ".join(text_commands)
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        f"5 0 obj << /Length {len(content)} >> stream\n{content}\nendstream endobj",
    ]
    parts = ["%PDF-1.4\n"]
    offsets = [0]
    for item in objects:
        offsets.append(sum(len(part.encode("latin1")) for part in parts))
        parts.append(item + "\n")
    xref_start = sum(len(part.encode("latin1")) for part in parts)
    parts.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        parts.append(f"{offset:010d} 00000 n \n")
    parts.append(
        f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_start}\n%%EOF\n"
    )
    path.write_bytes("".join(parts).encode("latin1"))
