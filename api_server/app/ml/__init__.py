"""Worker-only machine-learning boundary.

API route and service modules must not import model runtimes from this package. The
separate worker owns local model loading and inference.
"""

