import argparse
import json
from pathlib import Path

import pytest

from benchmarks.run_comparison import (
    AgentSpec,
    _usage_from_claude,
    _usage_from_codex,
    agent_prompt,
    extract_answer,
    parse_agent_spec,
    score_answer,
    write_summary,
)


def test_agent_specs_support_anthropic_and_openai():
    assert parse_agent_spec("anthropic:claude-example") == AgentSpec(
        "anthropic", "claude-example")
    assert parse_agent_spec("openai:gpt-example") == AgentSpec(
        "openai", "gpt-example")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_agent_spec("other:model")


def test_source_prompt_gets_exact_configuration_and_strong_tools():
    config = {
        "id": "d",
        "label": "Exact design",
        "configuration": "rv32",
        "load": {"top": "top", "flist": "/src/files.f"},
        "environment": {"TARGET_CFG": "rv32"},
        "source_guidance": ["Follow parameter flow."],
    }
    prompt = agent_prompt(
        "source", {"question": "How many?"}, config,
        {"revision": "abc123", "dirty": False})
    assert "Configuration: rv32" in prompt
    assert "TARGET_CFG=rv32" in prompt
    assert "revision: abc123" in prompt
    assert "rg/grep" in prompt
    assert "read-only scripts" in prompt
    assert "parameter flow" in prompt


def test_extract_answer_keeps_multiline_answer():
    text = "work\nANSWER: first line\nsecond line"
    assert extract_answer(text) == "first line\nsecond line"


def test_primary_numeric_does_not_accept_expected_number_after_wrong_answer():
    status, _ = score_answer(
        "ANSWER: 56 in this configuration; 34 in RV32.",
        {"type": "primary_numeric", "value": 34})
    assert status == "fail"


def test_rejection_pattern_overrides_positive_match():
    status, _ = score_answer(
        "ANSWER: value 34, but the current configuration is 56",
        {"type": "contains_all", "terms": ["34"],
         "reject_patterns": ["current configuration is 56"]})
    assert status == "fail"


def test_config_sensitive_checks_reject_rv64_as_current_answer():
    config = json.loads(
        (Path(__file__).parents[1] / "benchmarks/cva6-cv32.json").read_text())
    questions = {item["id"]: item for item in config["questions"]}
    plen = (
        "ANSWER: PLEN is the physical-address width and depends on XLEN. "
        "For the standard RV64 configuration PLEN = 56; RV32 gives 34.")
    csr = (
        "ANSWER: SELECT_COUNTER_WIDTH depends on IS_XLEN64/XLEN. "
        "For the standard RV64 configuration SELECT_COUNTER_WIDTH = 6; "
        "RV32 gives 5.")
    assert score_answer(plen, questions["cva6-plen-param"]["check"])[0] == "fail"
    assert score_answer(
        csr, questions["cva6-csr-counter-width"]["check"])[0] == "fail"


def test_every_cva6_golden_passes_its_check():
    config = json.loads(
        (Path(__file__).parents[1] / "benchmarks/cva6-cv32.json").read_text())
    for question in config["questions"]:
        status, reason = score_answer(
            "ANSWER: " + question["golden"], question["check"])
        assert status == "pass", f"{question['id']}: {reason}"


def test_claude_usage_includes_helpers_and_cache_tokens():
    events = [{
        "type": "result",
        "num_turns": 3,
        "result": "ANSWER: yes",
        "modelUsage": {
            "main": {"inputTokens": 10, "cacheReadInputTokens": 20,
                     "cacheCreationInputTokens": 30, "outputTokens": 4},
            "helper": {"inputTokens": 1, "cacheReadInputTokens": 2,
                       "cacheCreationInputTokens": 3, "outputTokens": 5},
        },
    }]
    usage = _usage_from_claude(events)
    assert usage["input_tokens"] == 66
    assert usage["output_tokens"] == 9
    assert set(usage["model_usage"]) == {"main", "helper"}


def test_codex_cached_input_is_not_double_counted():
    events = [{"type": "turn.completed", "usage": {
        "input_tokens": 100, "cached_input_tokens": 80,
        "output_tokens": 20}}]
    usage = _usage_from_codex(events)
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 80
    assert usage["output_tokens"] == 20


def test_summary_records_requested_and_observed_models(tmp_path):
    metadata = {
        "design": {"label": "D"},
        "fingerprint": "abc",
        "agents": {"anthropic:requested": "Claude Code 1.2.3"},
        "effort": "high",
    }
    result = {
        "provider": "anthropic",
        "model": "requested",
        "arm": "source",
        "score": "pass",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "model_usage": {"resolved-main": {}, "helper": {}},
        },
        "tool_calls": 1,
        "wall_seconds": 2.5,
    }
    write_summary(tmp_path, metadata, [result])
    summary = (tmp_path / "summary.md").read_text()
    assert "Requested model" in summary
    assert "Models observed" in summary
    assert "`requested`" in summary
    assert "`resolved-main`" in summary
    assert "`helper`" in summary
    assert "Claude Code 1.2.3" in summary


def test_historical_token_totals_include_every_reported_model():
    history = json.loads(
        (Path(__file__).parents[1] /
         "benchmarks/historical-cva6-20260628.json").read_text())
    for arm in history["arms"].values():
        input_total = sum(
            usage["ordinary_input_tokens"] +
            usage["cache_creation_input_tokens"] +
            usage["cache_read_input_tokens"]
            for usage in arm["models"].values())
        output_total = sum(
            usage["output_tokens"] for usage in arm["models"].values())
        assert input_total == arm["all_model_input_processed"]
        assert output_total == arm["all_model_output_tokens"]
