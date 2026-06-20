"""ContractIQ-owned post-processors.

Importing this package registers all bundled bindings with
engine.post_processors. Wire it up by setting
POST_PROCESSOR_MODULES=contractiq.runtime.post_processors on the
agent-runtime pod (see helm values).
"""

from contractiq.runtime.post_processors import canonical_anchor  # noqa: F401
