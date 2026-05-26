# slide_maker

CrewAI Flow for turning a book chapter into a class PowerPoint deck.

## What It Does

- Accepts a PDF chapter file, optional PowerPoint template, desired slide count, and desired example-question count.
- Uses the CrewAI recommended Flow project layout with `main.py`, embedded crews, crew YAML config, and tools.
- Falls back to a deterministic local planner when CrewAI or live LLM credentials are unavailable, so each step can be tested locally.
- Extracts PDF text, extracts available embedded PDF images, and can also use a supplied image directory.
- Writes a `.pptx` output file.
- Exposes a Python API, CLI, and FastMCP-ready decorated tool.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For production CrewAI/FastMCP usage, install the base project dependencies:

```bash
pip install -r requirements.txt
```

You will also need to create a `.env` file in the root directory with the applicable key or keys

```bash
OPENAI_API_KEY=replace-me
ANTHROPIC_API_KEY=replace-me
GOOGLE_API_KEY=replace-me
GROQ_API_KEY=replace-me
```

## Run From CLI

```bash
slide-maker path/to/chapter.pdf \
  --output out/photosynthesis.pptx \
  --slides 6 \
  --questions 3 \
  --config examples/config.json
```

You can also run without installation:

```bash
PYTHONPATH=src python3 -m slide_maker.cli path/to/chapter.pdf --output out/deck.pptx --slides 5 --questions 2
```

## Run From Python

```python
from slide_maker import run

result = run(
    chapter_path="path/to/chapter.pdf",
    output_path="out/deck.pptx",
    slide_count=6,
    question_count=3,
    template_path=None,
    image_dir=None,
    config_path="examples/config.json",
    llm_profile="gemini_flash"
)
print(result.output_path)
```

## Directory Tree

This project follows the CrewAI Flow structure, with a small tools package for deterministic pipeline steps and a crew package for LLM-backed planning:

```text
.
├── README.md
├── pyproject.toml
├── requirements.txt
├── examples/
│   ├── config.json
│   └── example_chapter.pdf
├── src/
│   └── slide_maker/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── errors.py
│       ├── main.py
│       ├── mcp_server.py
│       ├── models.py
│       ├── crews/
│       │   └── slide_deck_crew/
│       │       ├── slide_deck_crew.py
│       │       └── config/
│       │           ├── agents.yaml
│       │           └── tasks.yaml
│       └── tools/
│           ├── chapter_ingest.py
│           ├── context_chunking.py
│           ├── deterministic_planner.py
│           ├── image_assignment.py
│           └── pptx_writer.py
└── tests/
    └── test_pipeline.py
```

When CrewAI is installed in the environment, you can use (**note:** it uses all defaults):

```bash
crewai run
```

## Workflow And Crew Kickoffs

This project has two orchestration layers:

```text
SlideMakerFlow
-> Python: load_config(...) 
-> Python: load_chapter(...)
-> Crew: analyze_chapter with Crew(...).kickoff()
-> Crew: create_slide_deck/create_slide_plan with Crew(...).kickoff()
-> Python: attach_images(...)
-> Python: write_pptx(...)
```

`src/slide_maker/main.py` owns the outer application flow. It handles the deterministic work that should stay in Python: loading files, passing state between steps, assigning images, and writing the final `.pptx`.

`src/slide_maker/crews/slide_deck_crew/slide_deck_crew.py` owns the inner LLM crew work. It currently has two separate `Crew(...).kickoff()` calls:

- `_analyze_with_crewai(...)`: runs the `analyze_chapter` task with the instructional content analyst.
- `_plan_with_crewai(...)`: runs the `create_slide_plan` task with the slide designer, using the prior chapter analysis as context.

That means the full workflow is not one large CrewAI `Crew` with every step as an agent task. It is a CrewAI `Flow` for the application pipeline, with smaller CrewAI `Crew` runs inside the planning step where LLM reasoning is useful.

## Updating The Workflow

Use these files when changing or extending the slide-making pipeline:

- `src/slide_maker/main.py`: owns the top-level `SlideMakerFlow` order. Add, remove, or reorder workflow steps here with CrewAI `@start()` and `@listen()` methods. The current order is `ingest_chapter` -> `analyze_chapter` -> `create_slide_deck` -> `attach_book_images` -> `render_powerpoint`.
- `src/slide_maker/crews/slide_deck_crew/slide_deck_crew.py`: wires CrewAI agents and tasks into executable planning logic. Add a new agent to `_build_agents()`, load its YAML config from `agents.yaml`, and include it in the `Crew(agents=[...])` list for the task that should use it.
- `src/slide_maker/crews/slide_deck_crew/config/agents.yaml`: update agent roles, goals, and backstories here. Add a new top-level key for each new CrewAI agent, then reference that key from `_build_agents()`.
- `src/slide_maker/crews/slide_deck_crew/config/tasks.yaml`: update LLM task instructions, expected output text, JSON schemas, and formatting rules here. If you add a new task, add a new top-level task key and create the matching `Task(...)` object in `slide_deck_crew.py`.
- `src/slide_maker/tools/`: put reusable deterministic helpers here. Tools that are part of the pipeline should expose plain Python functions and be imported by `main.py` or `slide_deck_crew.py`.
- `src/slide_maker/models.py`: update shared dataclasses when the workflow needs to pass new structured data between steps, such as new slide fields or analysis fields.
- `src/slide_maker/config.py` and `examples/config.json`: update runtime configuration, orchestration settings, and LLM profiles here.
- `src/slide_maker/cli.py`: update command-line flags when a new workflow input should be available from the CLI.
- `src/slide_maker/mcp_server.py`: update the FastMCP wrapper when a new input or output should be exposed through the MCP tool.
- `tests/test_pipeline.py`: add or update tests for any new tool, flow step, schema field, or fallback behavior.

When adding a new tool:

1. Create the implementation under `src/slide_maker/tools/`.
2. Import and call it from the workflow step that needs it, usually in `src/slide_maker/main.py`.
3. Add or adjust dataclasses in `src/slide_maker/models.py` if the tool passes new structured data to another step.
4. Add focused coverage in `tests/test_pipeline.py`.

When adding a new agent or CrewAI task:

1. Add the agent definition to `src/slide_maker/crews/slide_deck_crew/config/agents.yaml`.
2. Add or update task instructions in `src/slide_maker/crews/slide_deck_crew/config/tasks.yaml`.
3. Update `_build_agents()` in `src/slide_maker/crews/slide_deck_crew/slide_deck_crew.py`.
4. Create or update the matching `Task(...)` and `Crew(...)` wiring in `slide_deck_crew.py`.
5. Keep the deterministic fallback in `src/slide_maker/tools/deterministic_planner.py` compatible when tests or offline usage depend on the same behavior.

## FastMCP Wrapper

`src/slide_maker/mcp_server.py` defines a decorated `make_slides` tool when `fastmcp` is installed.

```bash
fastmcp run src/slide_maker/mcp_server.py:mcp
```

## LLM Config

See `examples/config.json`. Add profiles under `llms` and pick them with `default_llm` or the CLI `--llm-profile` flag.

Supported profile fields:

- `provider`: provider namespace, such as `openai`, `anthropic`, or `ollama`.
- `model`: model name.
- `temperature`: generation temperature.
- `api_key_env`: environment variable containing the key.
- `base_url`: optional provider endpoint for local or compatible APIs.
- `extra`: optional provider-specific CrewAI LLM kwargs.

Included example profiles:

- `openai_fast`
- `anthropic_sonnet`
- `gemini_flash`
- `groq_llama`
- `ollama_local`

For Gemini, set `GOOGLE_API_KEY` in `.env`. For Groq, set `GROQ_API_KEY`.

## Testing Each Step

```bash
pytest
```

Tests cover:

- chapter ingestion for PDF text and Markdown/image-directory compatibility
- slide/question planning
- image assignment
- PowerPoint package writing
- full workflow execution without a live LLM

## Current Template Behavior

The renderer uses `python-pptx` by default. When a template path is supplied, the presentation is created from that template and generated slides are added with the template's blank layout when available.
