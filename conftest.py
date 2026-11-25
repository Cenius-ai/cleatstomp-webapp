"""Make the single-file tool importable from the tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
