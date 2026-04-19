import os
import sys

# Add the parent directory (python-2l-c) to sys.path so `import turret_placer` works.
HERE = os.path.dirname(__file__)
PARENT = os.path.abspath(os.path.join(HERE, ".."))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
