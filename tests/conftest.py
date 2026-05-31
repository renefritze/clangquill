"""Makes sure all our fixtures are available to all tests

Individual test modules MUST NOT import fixtures from `tests.fixtures`,
as this can have strange side effects.
"""
pytest_plugins = [
    "tests.fixtures",
]
