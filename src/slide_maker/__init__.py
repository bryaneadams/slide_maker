"""CrewAI Flow for chapter-to-slide generation."""

__all__ = ["SlideMakerFlow", "run"]


def __getattr__(name: str):
    if name in __all__:
        from slide_maker.main import SlideMakerFlow, run

        return {"SlideMakerFlow": SlideMakerFlow, "run": run}[name]
    raise AttributeError(name)
