from __future__ import annotations

import re
from dataclasses import replace

from slide_maker.models import BookImage, Slide, SlideDeck


def attach_images(deck: SlideDeck, images: tuple[BookImage, ...]) -> SlideDeck:
    if not images:
        return deck

    unused = list(images)
    updated: list[Slide] = []
    for slide in deck.slides:
        image = _best_image(slide, unused)
        if image is None:
            updated.append(slide)
            continue
        unused.remove(image)
        updated.append(replace(slide, image_path=image.path))
    return replace(deck, slides=tuple(updated))


def _best_image(slide: Slide, images: list[BookImage]) -> BookImage | None:
    slide_words = _tokens(" ".join((slide.title, *slide.bullets)))
    best: tuple[int, BookImage] | None = None
    for image in images:
        image_words = _tokens(f"{image.alt_text} {image.path.stem}")
        score = len(slide_words & image_words)
        if score and (best is None or score > best[0]):
            best = (score, image)
    return best[1] if best else images[0] if not any(slide.image_path for slide in []) else None


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-zA-Z]{4,}", text.lower())}
