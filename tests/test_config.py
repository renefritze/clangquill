"""Tests for the shared configuration dataclass and its validation."""

from __future__ import annotations

import pytest

from clangquill.config import CONFIG_FIELDS, CONFIG_PREFIX, Config, ConfigError


def test_defaults_match_issue_contract():
    cfg = Config(input=["a.hpp"])
    assert cfg.output_dir == "api"
    assert cfg.include_undocumented is True
    assert cfg.group_by == "symbol"
    assert cfg.std == "c++20"
    assert cfg.toctree_maxdepth == 2
    assert cfg.root_document == "index"


def test_config_fields_cover_every_documented_value():
    names = {name for name, _ in CONFIG_FIELDS}
    expected = {
        "clangquill_input",
        "clangquill_compile_commands",
        "clangquill_compile_args",
        "clangquill_include_dirs",
        "clangquill_std",
        "clangquill_defines",
        "clangquill_clang_resource_dir",
        "clangquill_output_dir",
        "clangquill_template_dirs",
        "clangquill_templates",
        "clangquill_cache_dir",
        "clangquill_include_undocumented",
        "clangquill_comment_parser",
        "clangquill_group_by",
        "clangquill_toctree_maxdepth",
        "clangquill_root_document",
    }
    assert expected <= names
    assert all(name.startswith(CONFIG_PREFIX) for name in names)


def test_from_mapping_strips_prefix_and_normalises_input():
    cfg = Config.from_mapping(
        {
            "clangquill_input": "single.hpp",
            "clangquill_std": "c++23",
            "unrelated_key": "ignored",
        },
    )
    assert cfg.input == ["single.hpp"]
    assert cfg.std == "c++23"


def test_validate_rejects_empty_input():
    with pytest.raises(ConfigError, match="at least one"):
        Config(input=[]).validate()


def test_validate_rejects_unknown_group_by():
    with pytest.raises(ConfigError, match="group_by"):
        Config(input=["a.hpp"], group_by="nonsense").validate()


def test_validate_rejects_bad_maxdepth():
    with pytest.raises(ConfigError, match="toctree_maxdepth"):
        Config(input=["a.hpp"], toctree_maxdepth=0).validate()


def test_validate_returns_self():
    cfg = Config(input=["a.hpp"])
    assert cfg.validate() is cfg
