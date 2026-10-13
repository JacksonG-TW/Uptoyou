"""D39's generator: a place's category, produced offline and validated before it is written.

The package splits three ways on purpose. `categories` holds D38's closed list and the
validation D39 rests on; `prompt` holds the version-controlled instruction, which is the
*Skill / Tool / Prompt* artifact the requirements analysis names; `classify` is the pure step —
a name and a way to ask a model in, one validated category or a stated refusal out.

Nothing here reaches a database or a network. The runner that does both is separate, for
the same reason D43 keeps contributors pure: what can be replayed can be audited.
"""

from upto.classify.categories import CATEGORIES, is_valid
from upto.classify.classify import (
    Classified,
    NoSignal,
    Refused,
    classify_name,
    classify_name_rag,
)
from upto.classify.prompt import (
    NO_SIGNAL,
    PROMPT_VERSION,
    RAG_PROMPT_VERSION,
    build,
    build_rag,
)

# `embed` and `examples` are deliberately absent. The second reaches SQLAlchemy and the host
# Python that runs the score tests has none, so importing this package must stay free of it;
# D88's retrieval path imports those two modules by name, where it needs them.
__all__ = [
    "CATEGORIES",
    "Classified",
    "NO_SIGNAL",
    "NoSignal",
    "PROMPT_VERSION",
    "RAG_PROMPT_VERSION",
    "Refused",
    "build",
    "build_rag",
    "classify_name",
    "classify_name_rag",
    "is_valid",
]
