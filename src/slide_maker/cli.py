from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from slide_maker.errors import SlideMakerError
from slide_maker.main import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a PowerPoint deck from a book chapter."
    )
    parser.add_argument("chapter", help="Path to .txt or .md chapter content.")
    parser.add_argument("--output", required=True, help="Output .pptx path.")
    parser.add_argument(
        "--slides", type=int, required=True, help="Number of slides to generate."
    )
    parser.add_argument(
        "--questions", type=int, default=0, help="Number of example questions."
    )
    parser.add_argument("--template", help="Optional PowerPoint template path.")
    parser.add_argument(
        "--image-dir", help="Optional directory of extracted book images."
    )
    parser.add_argument("--config", help="Optional JSON/YAML config path.")
    parser.add_argument("--llm-profile", help="Named LLM profile from config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(
            chapter_path=args.chapter,
            output_path=args.output,
            slide_count=args.slides,
            question_count=args.questions,
            template_path=args.template,
            image_dir=args.image_dir,
            config_path=args.config,
            llm_profile=args.llm_profile,
        )
    except SlideMakerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "output_path": str(Path(result.output_path).resolve()),
                "slide_count": len(result.deck.slides),
                "question_count": len(result.deck.questions),
                "warnings": list(result.warnings),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
