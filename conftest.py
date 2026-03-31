# conftest.py  ← taruh di root project (sejajar dengan folder controller, service, dll)
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
