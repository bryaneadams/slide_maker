from __future__ import annotations

from slide_maker.main import run

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None


if FastMCP is not None:
    mcp = FastMCP("slide-maker")

    @mcp.tool
    def make_slides(
        chapter_path: str,
        output_path: str,
        slide_count: int,
        question_count: int,
        template_path: str | None = None,
        image_dir: str | None = None,
        config_path: str | None = None,
        llm_profile: str | None = None,
    ) -> dict:
        """Create a PowerPoint teaching deck from a chapter file.

        Use this when the user provides a PDF, Markdown, or text chapter and wants a generated `.pptx` deck. The tool can use an optional PowerPoint template, optional extracted book images, and optional LLM config/profile settings. `slide_count` is the total number of slides to generate. `question_count` controls how many final slides should be example questions.
        """
        result = run(
            chapter_path=chapter_path,
            output_path=output_path,
            slide_count=slide_count,
            question_count=question_count,
            template_path=template_path,
            image_dir=image_dir,
            config_path=config_path,
            llm_profile=llm_profile,
        )
        return {
            "output_path": str(result.output_path),
            "slide_count": len(result.deck.slides),
            "question_count": len(result.deck.questions),
            "warnings": list(result.warnings),
        }

else:
    mcp = None
