from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from slide_maker.errors import InputValidationError
from slide_maker.models import BookImage, Chapter

IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def load_chapter(
    chapter_path: str | Path, image_dir: str | Path | None = None
) -> Chapter:
    """loads the chapter

    Args:
        chapter_path (str | Path): path to the chapter
        image_dir (str | Path | None, optional): path to and imagery directory. Defaults to None.

    Raises:
        InputValidationError: File does not exist
        InputValidationError: File not in a valid file format

    Returns:
        Chapter: The ingested chapter
    """
    path = Path(chapter_path)
    if not path.exists():
        raise InputValidationError(f"Chapter file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        chapter = _load_text_chapter(path)
        images = list(chapter.images)
        text = chapter.text
        title = chapter.title
    elif suffix == ".pdf":
        chapter = _load_pdf_chapter(path)
        images = list(chapter.images)
        text = chapter.text
        title = chapter.title
    else:
        raise InputValidationError(
            "Chapter input supports .pdf, .txt, .md, and .markdown files."
        )

    if image_dir is not None:
        images.extend(_images_from_directory(Path(image_dir)))
    return Chapter(title=title, text=text, images=tuple(dict.fromkeys(images)))


def _load_text_chapter(path: Path) -> Chapter:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise InputValidationError("Chapter file is empty.")
    return Chapter(
        title=_title_from_text(text, path.stem),
        text=text,
        images=_images_from_markdown(text, path.parent),
    )


def _load_pdf_chapter(path: Path) -> Chapter:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise InputValidationError(
            "PDF chapters require the pypdf package. Install requirements.txt."
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise InputValidationError(f"Could not read PDF chapter: {path}") from exc

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            raise InputValidationError(
                f"Could not extract text from PDF page {index}."
            ) from exc
        if page_text.strip():
            pages.append(page_text.strip())

    text = "\n\n".join(pages).strip()
    if not text:
        raise InputValidationError("PDF chapter contains no extractable text.")

    return Chapter(
        title=_pdf_title(reader, text, path.stem),
        text=text,
        images=_extract_pdf_images(reader, path),
    )


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            return clean.lstrip("#").strip() or fallback
        if clean:
            return clean[:80]
    return fallback


def _images_from_markdown(text: str, base_dir: Path) -> tuple[BookImage, ...]:
    images: list[BookImage] = []
    for match in IMAGE_RE.finditer(text):
        raw_path = match.group("path").strip()
        if raw_path.startswith(("http://", "https://")):
            continue
        image_path = (base_dir / raw_path).resolve()
        if image_path.exists():
            images.append(
                BookImage(
                    path=image_path,
                    alt_text=match.group("alt").strip(),
                    source="markdown",
                )
            )
    return tuple(images)


def _images_from_directory(image_dir: Path) -> tuple[BookImage, ...]:
    if not image_dir.exists():
        raise InputValidationError(f"Image directory does not exist: {image_dir}")
    return tuple(
        BookImage(
            path=path.resolve(),
            alt_text=path.stem.replace("_", " "),
            source="image_dir",
        )
        for path in sorted(image_dir.iterdir())
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()
    )


def _pdf_title(reader, text: str, fallback: str) -> str:
    metadata_title = getattr(getattr(reader, "metadata", None), "title", None)
    if metadata_title:
        return str(metadata_title).strip()[:120]
    return _title_from_text(text, fallback)


def _extract_pdf_images(reader, pdf_path: Path) -> tuple[BookImage, ...]:
    output_dir = pdf_path.parent / f"{pdf_path.stem}_images"
    images: list[BookImage] = []
    for page_number, page in enumerate(reader.pages, start=1):
        for image_number, image_file_object in enumerate(_page_images(page), start=1):
            name = _pdf_image_name(
                pdf_path.stem, page_number, image_number, image_file_object
            )
            image_path = output_dir / name
            try:
                data = image_file_object.data
            except Exception:
                continue
            output_dir.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(data)
            images.append(
                BookImage(
                    path=image_path.resolve(),
                    alt_text=f"{pdf_path.stem} page {page_number} image {image_number}",
                    source="pdf",
                )
            )
    return tuple(images)


def _page_images(page) -> Iterable:
    try:
        return page.images
    except Exception:
        return ()


def _pdf_image_name(
    pdf_stem: str, page_number: int, image_number: int, image_file_object
) -> str:
    raw_name = getattr(image_file_object, "name", "") or ""
    suffix = Path(raw_name).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".png"
    return f"{pdf_stem}_page_{page_number}_image_{image_number}{suffix}"
