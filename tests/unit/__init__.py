"""Unit tests for Mahavishnu.

Packageizing this directory gives every test module a dotted name
(``tests.unit.<dir>.<module>``) instead of a bare basename. Pytest's
default import mode derives the module name from the file's path only
as far as the nearest directory that has an ``__init__.py``; without
this file, two test files anywhere under ``tests/unit`` that share a
basename collide ("import file mismatch"), and which pair collides
depends on collection order.
"""
