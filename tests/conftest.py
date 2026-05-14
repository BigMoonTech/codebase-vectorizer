"""Shared pytest fixtures for codebase-vectorizer tests.

Populated incrementally across Slice 1 tasks. Slice 1 ends with at
least the tmp_data_home and stub_embedder fixtures.

`collect_ignore` excludes the fixture tree from pytest discovery. The
fixture's own tests/ subdir is a sample test file shipped INSIDE the
fixture; we do NOT want pytest to collect it at the cbv project level
(it imports from `pkg`, a path only valid inside the fixture itself).
"""

collect_ignore = ["fixtures"]
