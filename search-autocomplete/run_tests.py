#!/usr/bin/env python3
"""Run: python3 -m pytest test_search_autocomplete.py -v"""
import sys
import pytest
sys.exit(pytest.main([__file__.replace("run_tests.py", "test_search_autocomplete.py"), "-v"]))
