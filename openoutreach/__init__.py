# pydantic-ai 2.x renamed `OpenAIModel` to `OpenAIChatModel` and dropped the old
# name, while both children (openoutfind, openoutsend) are written against the
# 1.x spelling yet declare `pydantic-ai-slim>=2,<3` — so every fresh resolution
# lands on a 2.x whose `models.openai` module no longer has the name their code
# imports. Alias it back here, in the host package: this module is imported
# before anything under `openoutreach` touches either child, and before Django
# hosts their apps, so every bundled entry point (CLI, manage.py, Docker, CI)
# repairs the name before a child can reach for it.
try:
    import pydantic_ai.models.openai as _pai_openai
    if not hasattr(_pai_openai, "OpenAIModel"):
        _pai_openai.OpenAIModel = _pai_openai.OpenAIChatModel
except ImportError:  # pragma: no cover - pydantic-ai is a hard child dependency
    pass
