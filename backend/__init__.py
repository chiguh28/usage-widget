"""backend: pure, GUI-free core for usage-widget.

Only backend.ccusage_client touches subprocess; everything else here is pure
functions over dataclasses/dicts (model, normalize, aggregate, export).
"""
