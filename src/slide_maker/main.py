from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field

from slide_maker.config import SlideMakerConfig, load_config
from slide_maker.crews.slide_deck_crew import SlideDeckCrew
from slide_maker.models import Chapter, ChapterAnalysis, SlideDeck, WorkflowResult
from slide_maker.tools.chapter_ingest import load_chapter
from slide_maker.tools.image_assignment import attach_images
from slide_maker.tools.pptx_writer import write_pptx

try:
    from crewai.flow.flow import Flow, listen, start
except (
    ImportError
):  # pragma: no cover - keeps unit tests runnable without CrewAI installed

    class Flow:
        """Minimal stand-in for CrewAI Flow when CrewAI is not installed."""

        def __class_getitem__(cls, _item):
            """Support generic `Flow[State]` syntax in fallback mode.

            Args:
                _item: Ignored type parameter.

            Returns:
                type: The fallback Flow class.
            """
            return cls

        def __init__(self, **kwargs):
            """Initialize a fallback flow with optional state values.

            Args:
                **kwargs: State field values passed by the caller.
            """
            self.state = SimpleNamespace(**kwargs)

    def start():
        """Return a no-op replacement for CrewAI's `@start()` decorator.

        Returns:
            function: Decorator that returns the wrapped function unchanged.
        """

        def decorator(func):
            """Return a flow step unchanged.

            Args:
                func: Function decorated as a start step.

            Returns:
                function: The original function.
            """
            return func

        return decorator

    def listen(_source):
        """Return a no-op replacement for CrewAI's `@listen()` decorator.

        Args:
            _source: Upstream flow step ignored by the fallback decorator.

        Returns:
            function: Decorator that returns the wrapped function unchanged.
        """

        def decorator(func):
            """Return a flow step unchanged.

            Args:
                func: Function decorated as a listener step.

            Returns:
                function: The original function.
            """
            return func

        return decorator


class SlideMakerState(BaseModel):
    """Mutable state passed between SlideMaker flow steps."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chapter_path: str = ""
    output_path: str = ""
    slide_count: int = 0
    question_count: int = 0
    template_path: str | None = None
    image_dir: str | None = None
    config_path: str | None = None
    llm_profile: str | None = None
    config: SlideMakerConfig | None = None
    chapter: Chapter | None = None
    analysis: ChapterAnalysis | None = None
    deck: SlideDeck | None = None
    warnings: list[str] = Field(default_factory=list)


class SlideMakerFlow(Flow[SlideMakerState]):
    """CrewAI Flow that turns a chapter into a rendered PowerPoint deck."""

    @start()
    def ingest_chapter(self) -> Chapter:
        """Load runtime config and ingest the source chapter.

        Returns:
            Chapter: Loaded chapter text and extracted image metadata.
        """
        self.state.config = load_config(self.state.config_path)
        chapter = load_chapter(self.state.chapter_path, image_dir=self.state.image_dir)
        self.state.chapter = chapter
        return chapter

    @listen(ingest_chapter)
    def analyze_chapter(self, chapter: Chapter) -> ChapterAnalysis:
        """Analyze the ingested chapter for teaching structure.

        Args:
            chapter (Chapter): Chapter returned by the ingest step.

        Returns:
            ChapterAnalysis: Teaching analysis from CrewAI or deterministic
                fallback.
        """
        analysis = SlideDeckCrew(self.state.config).analyze_chapter(
            chapter=chapter,
            llm_profile=self.state.llm_profile,
        )
        self.state.analysis = analysis
        return analysis

    @listen(analyze_chapter)
    def create_slide_deck(self, analysis: ChapterAnalysis) -> SlideDeck:
        """Create slide content from the chapter analysis.

        Args:
            analysis (ChapterAnalysis): Analysis returned by the prior step.

        Raises:
            RuntimeError: If the chapter was not loaded before this step.

        Returns:
            SlideDeck: Planned deck from CrewAI or deterministic fallback.
        """
        if self.state.chapter is None:
            raise RuntimeError("Chapter was not loaded before slide planning.")
        deck = SlideDeckCrew(self.state.config).create_slide_deck(
            chapter=self.state.chapter,
            analysis=analysis,
            slide_count=self.state.slide_count,
            question_count=self.state.question_count,
            llm_profile=self.state.llm_profile,
        )
        self.state.deck = deck
        return deck

    @listen(create_slide_deck)
    def attach_book_images(self, deck: SlideDeck) -> SlideDeck:
        """Attach extracted book images to planned slides.

        Args:
            deck (SlideDeck): Planned deck before image assignment.

        Raises:
            RuntimeError: If the chapter was not loaded before this step.

        Returns:
            SlideDeck: Deck with image paths assigned where available.
        """
        if self.state.chapter is None:
            raise RuntimeError("Chapter was not loaded before image assignment.")
        deck_with_images = attach_images(deck, self.state.chapter.images)
        self.state.deck = deck_with_images
        return deck_with_images

    @listen(attach_book_images)
    def render_powerpoint(self, deck: SlideDeck) -> WorkflowResult:
        """Render the final slide deck to a PowerPoint file.

        Args:
            deck (SlideDeck): Deck after image assignment.

        Returns:
            WorkflowResult: Output path, rendered deck, and render warnings.
        """
        output, render_warnings = write_pptx(
            deck,
            self.state.output_path,
            template_path=self.state.template_path,
        )
        self.state.warnings.extend(render_warnings)
        return WorkflowResult(
            output_path=output, deck=deck, warnings=tuple(self.state.warnings)
        )


def run(
    chapter_path: str | Path,
    output_path: str | Path,
    slide_count: int,
    question_count: int,
    template_path: str | Path | None = None,
    image_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    llm_profile: str | None = None,
) -> WorkflowResult:
    """Run the full slide-making flow for one chapter.

    The flow loads configuration, ingests the chapter PDF, plans the deck with CrewAI or the deterministic fallback, assigns extracted images, and writes the final PowerPoint file.

    Args:
        chapter_path (str | Path): Path to the chapter PDF, Markdown, or text file.
        output_path (str | Path): Destination `.pptx` path.
        slide_count (int): Number of slides to generate.
        question_count (int): Number of example questions to include.
        template_path (str | Path | None, optional): Optional PowerPoint template path. Defaults to None.
        image_dir (str | Path | None, optional): Optional directory of extra book images. Defaults to None.
        config_path (str | Path | None, optional): Optional JSON/YAML config path. Defaults to None.
        llm_profile (str | None, optional): Optional named LLM profile from config. Defaults to None.

    Returns:
        WorkflowResult: Output path, generated deck, and any warnings.
    """
    state = SlideMakerState(
        chapter_path=str(chapter_path),
        output_path=str(output_path),
        slide_count=slide_count,
        question_count=question_count,
        template_path=str(template_path) if template_path else None,
        image_dir=str(image_dir) if image_dir else None,
        config_path=str(config_path) if config_path else None,
        llm_profile=llm_profile,
    )
    flow = SlideMakerFlow(**state.model_dump())
    return flow.render_powerpoint(
        flow.attach_book_images(
            flow.create_slide_deck(flow.analyze_chapter(flow.ingest_chapter()))
        )
    )


def kickoff() -> WorkflowResult:
    """Run the default CrewAI kickoff entrypoint.

    Returns:
        WorkflowResult: Result from running the example chapter workflow.
    """
    return run(
        chapter_path="examples/chapter.md",
        output_path="out/deck.pptx",
        slide_count=6,
        question_count=3,
        config_path="examples/config.json",
    )


def plot() -> None:
    """Generate a CrewAI flow plot for the slide maker workflow."""
    flow = SlideMakerFlow()
    flow.plot("SlideMakerFlowPlot")


if __name__ == "__main__":
    kickoff()
