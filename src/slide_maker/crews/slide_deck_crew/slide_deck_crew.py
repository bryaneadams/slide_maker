from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from slide_maker.config import SlideMakerConfig
from slide_maker.errors import OrchestrationError
from slide_maker.models import Chapter, ChapterAnalysis, SlideDeck
from slide_maker.tools.context_chunking import chunk_text_for_llm
from slide_maker.tools.deterministic_planner import plan_deck


class SlideDeckCrew:
    """Embedded CrewAI crew for chapter-to-slide planning."""

    def __init__(self, config: SlideMakerConfig):
        self.config = config

    def plan(
        self,
        chapter: Chapter,
        slide_count: int,
        question_count: int,
        llm_profile: str | None = None,
    ) -> SlideDeck:
        """Analyze a chapter and produce a complete slide deck plan.

        Args:
            chapter (Chapter): Loaded chapter text and extracted image metadata.
            slide_count (int): Target number of slides to create.
            question_count (int): Number of final question slides to include.
            llm_profile (str | None, optional): Named LLM profile from config.
                Defaults to None.

        Returns:
            SlideDeck: Planned deck with slides, questions, warnings, and LLM
                usage metadata.
        """
        analysis = self.analyze_chapter(chapter, llm_profile=llm_profile)
        deck = self.create_slide_deck(
            chapter=chapter,
            analysis=analysis,
            slide_count=slide_count,
            question_count=question_count,
            llm_profile=llm_profile,
        )
        return deck

    def analyze_chapter(
        self,
        chapter: Chapter,
        llm_profile: str | None = None,
    ) -> ChapterAnalysis:
        """Extract teaching-oriented analysis from chapter text.

        Args:
            chapter (Chapter): Loaded chapter to analyze.
            llm_profile (str | None, optional): Named LLM profile from config.
                Defaults to None.

        Raises:
            OrchestrationError: If CrewAI is unavailable and deterministic
                fallback is disabled.
            OrchestrationError: If the CrewAI analysis step fails and fallback
                is disabled.

        Returns:
            ChapterAnalysis: Summary, concepts, terms, questions, and cautions
                for downstream slide planning.
        """
        if self.config.orchestration.mode != "crewai":
            return _deterministic_analysis(chapter)
        try:
            return self._analyze_with_crewai(chapter, llm_profile)
        except ImportError as exc:
            if self.config.orchestration.allow_deterministic_fallback:
                return _deterministic_analysis(chapter)
            raise OrchestrationError(
                "CrewAI is not installed. Install project dependencies or enable deterministic fallback."
            ) from exc
        except Exception as exc:
            if self.config.orchestration.allow_deterministic_fallback:
                return _deterministic_analysis(chapter)
            raise OrchestrationError(f"CrewAI analysis step failed: {exc}") from exc

    def create_slide_deck(
        self,
        chapter: Chapter,
        analysis: ChapterAnalysis,
        slide_count: int,
        question_count: int,
        llm_profile: str | None = None,
    ) -> SlideDeck:
        """Create a slide deck from a chapter and prior analysis.

        Args:
            chapter (Chapter): Source chapter for slide content.
            analysis (ChapterAnalysis): Teaching analysis to guide slide sequencing and emphasis.
            slide_count (int): Target number of slides to create.
            question_count (int): Number of final question slides to include.
            llm_profile (str | None, optional): Named LLM profile from config. Defaults to None.

        Raises:
            OrchestrationError: If CrewAI is unavailable and deterministic fallback is disabled.
            OrchestrationError: If the CrewAI planning step fails and fallback is disabled.

        Returns:
            SlideDeck: Planned slide deck, produced by CrewAI or deterministic fallback depending on configuration.
        """
        if self.config.orchestration.mode != "crewai":
            deck = plan_deck(chapter, slide_count, question_count)
            return replace(
                deck,
                warnings=deck.warnings
                + (
                    _context_warning(
                        chapter.text, self.config.orchestration.max_context_tokens
                    ),
                ),
            )
        try:
            deck = self._plan_with_crewai(
                chapter, analysis, slide_count, question_count, llm_profile
            )
            return replace(
                deck,
                warnings=deck.warnings
                + (
                    _context_warning(
                        chapter.text, self.config.orchestration.max_context_tokens
                    ),
                ),
            )
        except ImportError as exc:
            if self.config.orchestration.allow_deterministic_fallback:
                deck = plan_deck(chapter, slide_count, question_count)
                return replace(
                    deck,
                    warnings=deck.warnings
                    + (
                        _context_warning(
                            chapter.text, self.config.orchestration.max_context_tokens
                        ),
                    ),
                )
            raise OrchestrationError(
                "CrewAI is not installed. Install project dependencies or enable deterministic fallback."
            ) from exc
        except Exception as exc:
            if self.config.orchestration.allow_deterministic_fallback:
                deck = plan_deck(chapter, slide_count, question_count)
                return replace(
                    deck,
                    warnings=deck.warnings
                    + (
                        _context_warning(
                            chapter.text, self.config.orchestration.max_context_tokens
                        ),
                    ),
                )
            raise OrchestrationError(f"CrewAI planning step failed: {exc}") from exc

    def _plan_with_crewai(
        self,
        chapter: Chapter,
        analysis: ChapterAnalysis,
        slide_count: int,
        question_count: int,
        llm_profile: str | None,
    ) -> SlideDeck:
        """Run the CrewAI slide-planning task and parse its JSON output.

        Args:
            chapter (Chapter): Source chapter for slide planning.
            analysis (ChapterAnalysis): Structured analysis from the analyst task.
            slide_count (int): Target number of slides to request.
            question_count (int): Number of final question slides to request.
            llm_profile (str | None): Named LLM profile from config.

        Returns:
            SlideDeck: Parsed slide deck marked as LLM-generated.
        """
        from crewai import Agent, Crew, Process, Task

        agent_config = _load_yaml_config("agents.yaml")
        task_config = _load_yaml_config("tasks.yaml")
        chunked_context = chunk_text_for_llm(
            chapter.text,
            max_tokens=self.config.orchestration.max_context_tokens,
        )

        llm = self._crewai_llm(llm_profile)
        analyst, designer = self._build_agents(agent_config, llm)
        task_template = task_config["create_slide_plan"]
        task = Task(
            description=task_template["description"].format(
                slide_count=slide_count,
                question_count=question_count,
                chapter_title=chapter.title,
                chapter_analysis=_analysis_to_json(analysis),
                chapter_text=chunked_context.text,
            ),
            expected_output=task_template["expected_output"],
            agent=designer,
            context=[],
        )
        crew = Crew(
            agents=[analyst, designer],
            tasks=[task],
            process=Process.sequential,
            verbose=self.config.orchestration.verbose,
        )
        result = crew.kickoff()
        return replace(
            _deck_from_json(
                str(result),
                fallback_title=chapter.title,
                slide_count=slide_count,
                question_count=question_count,
            ),
            used_llm=True,
        )

    def _analyze_with_crewai(
        self,
        chapter: Chapter,
        llm_profile: str | None,
    ) -> ChapterAnalysis:
        """Run the CrewAI chapter-analysis task and parse its JSON output.

        Args:
            chapter (Chapter): Source chapter to analyze.
            llm_profile (str | None): Named LLM profile from config.

        Returns:
            ChapterAnalysis: Parsed analysis marked as LLM-generated.
        """
        from crewai import Crew, Process, Task

        agent_config = _load_yaml_config("agents.yaml")
        task_config = _load_yaml_config("tasks.yaml")
        chunked_context = chunk_text_for_llm(
            chapter.text,
            max_tokens=self.config.orchestration.max_context_tokens,
        )
        llm = self._crewai_llm(llm_profile)
        analyst, _designer = self._build_agents(agent_config, llm)
        task = Task(
            description=task_config["analyze_chapter"]["description"].format(
                chapter_title=chapter.title,
                chapter_text=chunked_context.text,
            ),
            expected_output=task_config["analyze_chapter"]["expected_output"],
            agent=analyst,
            context=[],
        )
        crew = Crew(
            agents=[analyst],
            tasks=[task],
            process=Process.sequential,
            verbose=self.config.orchestration.verbose,
        )
        result = crew.kickoff()
        return replace(_analysis_from_json(str(result)), used_llm=True)

    def _crewai_llm(self, llm_profile: str | None):
        """Build a CrewAI LLM instance from the configured profile.

        Args:
            llm_profile (str | None): Named profile to load, or None for the
                configured default profile.

        Returns:
            LLM: CrewAI LLM configured with provider, model, temperature, API
                key, base URL, and extra provider options.
        """
        from crewai import LLM

        cfg = self.config.llm(llm_profile)
        kwargs = {
            "model": _crewai_model_name(cfg.provider, cfg.model),
            "temperature": cfg.temperature,
        }
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        api_key = self.config.api_key_for(llm_profile)
        if api_key:
            kwargs["api_key"] = api_key
        kwargs.update(cfg.extra)
        return LLM(**kwargs)

    def _build_agents(self, agent_config: dict, llm):
        """Create the CrewAI agents used by the slide planning crew.

        Args:
            agent_config (dict): Parsed `agents.yaml` configuration.
            llm: CrewAI LLM instance shared by the agents.

        Returns:
            tuple: Instructional content analyst and slide designer agents.
        """
        from crewai import Agent

        analyst_config = agent_config["instructional_content_analyst"]
        designer_config = agent_config["slide_designer"]
        analyst = Agent(
            role=analyst_config["role"],
            goal=analyst_config["goal"],
            backstory=analyst_config["backstory"],
            llm=llm,
            verbose=self.config.orchestration.verbose,
        )
        designer = Agent(
            role=designer_config["role"],
            goal=designer_config["goal"],
            backstory=designer_config["backstory"],
            llm=llm,
            verbose=self.config.orchestration.verbose,
        )
        return analyst, designer


def _deck_from_json(
    raw: str,
    fallback_title: str,
    slide_count: int | None = None,
    question_count: int = 0,
) -> SlideDeck:
    """Parse a CrewAI JSON response into a `SlideDeck`.

    Args:
        raw (str): Raw CrewAI response, optionally wrapped with extra text.
        fallback_title (str): Title to use if the response does not include one.
        slide_count (int | None, optional): Expected total slide count.
            Defaults to None.
        question_count (int, optional): Expected number of final question
            slides. Defaults to 0.

    Raises:
        OrchestrationError: If no JSON object can be found in the response.
        OrchestrationError: If the parsed response contains no slides.

    Returns:
        SlideDeck: Sanitized deck with question slides normalized.
    """
    from slide_maker.models import ExampleQuestion, Slide

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise OrchestrationError("CrewAI did not return JSON.")
    data = json.loads(raw[start : end + 1])
    slides = tuple(
        Slide(
            title=_plain_slide_text(str(item["title"])),
            bullets=tuple(
                _plain_slide_text(str(bullet)) for bullet in item.get("bullets", [])
            ),
            speaker_notes=_plain_slide_text(str(item.get("speaker_notes", ""))),
        )
        for item in data.get("slides", [])
    )
    questions = tuple(
        ExampleQuestion(
            prompt=_plain_slide_text(str(item["prompt"])),
            answer=_plain_slide_text(str(item.get("answer", ""))),
        )
        for item in data.get("questions", [])
    )
    slides = _ensure_question_slides(slides, questions, slide_count, question_count)
    if not slides:
        raise OrchestrationError("CrewAI returned no slides.")
    return SlideDeck(
        title=_plain_slide_text(str(data.get("title") or fallback_title)),
        slides=slides,
        questions=questions,
        used_llm=True,
    )


def _analysis_from_json(raw: str) -> ChapterAnalysis:
    """Parse a CrewAI JSON response into a `ChapterAnalysis`.

    Args:
        raw (str): Raw CrewAI response, optionally wrapped with extra text.

    Raises:
        OrchestrationError: If no JSON object can be found in the response.

    Returns:
        ChapterAnalysis: Sanitized chapter analysis marked as LLM-generated.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise OrchestrationError("CrewAI did not return analysis JSON.")
    data = json.loads(raw[start : end + 1])
    return ChapterAnalysis(
        summary=_plain_slide_text(str(data.get("summary", ""))),
        key_concepts=tuple(
            _plain_slide_text(str(item)) for item in data.get("key_concepts", [])
        ),
        key_terms=tuple(
            _plain_slide_text(str(item)) for item in data.get("key_terms", [])
        ),
        example_questions=tuple(
            _plain_slide_text(str(item)) for item in data.get("example_questions", [])
        ),
        cautions=tuple(str(item) for item in data.get("cautions", [])),
        used_llm=True,
    )


def _load_yaml_config(file_name: str) -> dict:
    """Load a CrewAI YAML config file from this crew's config directory.

    Args:
        file_name (str): Name of the YAML file under `config/`.

    Raises:
        OrchestrationError: If PyYAML is not installed.
        OrchestrationError: If the YAML file does not contain a mapping.

    Returns:
        dict: Parsed YAML mapping.
    """
    path = Path(__file__).parent / "config" / file_name
    try:
        import yaml
    except ImportError as exc:
        raise OrchestrationError(
            "PyYAML is required to load CrewAI YAML config files."
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OrchestrationError(f"CrewAI config must be a mapping: {path}")
    return data


def _crewai_model_name(provider: str, model: str) -> str:
    """Format a configured provider/model pair for CrewAI's LLM wrapper.

    Args:
        provider (str): Provider namespace from config.
        model (str): Provider model name from config.

    Returns:
        str: CrewAI-compatible model identifier.
    """
    normalized = provider.lower().strip()
    if normalized in {"openai", "azure"}:
        return model
    if normalized == "gemini":
        normalized = "google"
    return f"{normalized}/{model}"


def _context_warning(text: str, max_tokens: int) -> str:
    """Build a warning describing the LLM context size used for a chapter.

    Args:
        text (str): Source chapter text.
        max_tokens (int): Maximum token budget for LLM context chunking.

    Returns:
        str: Human-readable context chunk and token estimate warning.
    """
    chunked = chunk_text_for_llm(text, max_tokens=max_tokens)
    return (
        f"LLM context built from {chunked.chunk_count} chunk(s); "
        f"approx {chunked.estimated_tokens} tokens before compression."
    )


def _analysis_to_json(analysis: ChapterAnalysis) -> str:
    """Serialize chapter analysis for insertion into a CrewAI task prompt.

    Args:
        analysis (ChapterAnalysis): Analysis to pass to the slide planner.

    Returns:
        str: ASCII JSON representation of the analysis.
    """
    return json.dumps(
        {
            "summary": analysis.summary,
            "key_concepts": list(analysis.key_concepts),
            "key_terms": list(analysis.key_terms),
            "example_questions": list(analysis.example_questions),
            "cautions": list(analysis.cautions),
        },
        ensure_ascii=True,
    )


def _ensure_question_slides(
    slides: tuple["Slide", ...],
    questions: tuple["ExampleQuestion", ...],
    slide_count: int | None,
    question_count: int,
) -> tuple["Slide", ...]:
    """Replace the final slide slots with normalized question slides.

    Args:
        slides (tuple[Slide, ...]): Parsed slides from the CrewAI response.
        questions (tuple[ExampleQuestion, ...]): Parsed question objects.
        slide_count (int | None): Requested total slide count, if known.
        question_count (int): Requested number of question slides.

    Returns:
        tuple[Slide, ...]: Slides trimmed to the requested total with question
            slides at the end.
    """
    from slide_maker.models import Slide

    if question_count <= 0 or not questions:
        return slides

    total = slide_count or len(slides)
    question_total = min(question_count, len(questions), total)
    content_total = max(total - question_total, 0)
    content_slides = slides[:content_total]
    question_slides = tuple(
        Slide(
            title=f"Question {index}",
            bullets=(question.prompt, f"Answer: {question.answer}"),
            speaker_notes=question.answer,
        )
        for index, question in enumerate(questions[:question_total], start=1)
    )
    return (content_slides + question_slides)[:total]


def _plain_slide_text(text: str) -> str:
    """Strip Markdown and bullet prefixes from model-generated slide text.

    Args:
        text (str): Raw text from a model or deterministic planner.

    Returns:
        str: Plain text suitable for PowerPoint rendering.
    """
    clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"[*_`~]+", "", clean)
    clean = re.sub(r"^\s*(?:[-*+]|\d+[.)]|\u2022)\s+", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _deterministic_analysis(chapter: Chapter) -> ChapterAnalysis:
    """Create a local, non-LLM chapter analysis fallback.

    Args:
        chapter (Chapter): Source chapter to summarize heuristically.

    Returns:
        ChapterAnalysis: Deterministic analysis marked as not LLM-generated.
    """
    paragraphs = [p.strip() for p in chapter.text.split("\n\n") if p.strip()]
    summary = paragraphs[0][:400] if paragraphs else chapter.title
    key_concepts = tuple([line[:120] for line in paragraphs[1:4]] or [chapter.title])
    key_terms = tuple(
        sorted(
            {
                word.strip(",.;:()").lower()
                for word in chapter.text.split()
                if len(word.strip(",.;:()")) > 6
            }
        )[:10]
    )
    example_questions = tuple(
        f"What is the main idea of section {idx + 1}?"
        for idx, _ in enumerate(paragraphs[1:4])
    ) or (f"What is the main idea of {chapter.title}?",)
    cautions = (
        "Verify key definitions against the source PDF.",
        "Confirm image references before placing them on slides.",
    )
    return ChapterAnalysis(
        summary=summary,
        key_concepts=key_concepts,
        key_terms=key_terms,
        example_questions=example_questions,
        cautions=cautions,
        used_llm=False,
    )
