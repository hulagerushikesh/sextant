"""Citation validity is checked mechanically, so it is tested mechanically."""

from __future__ import annotations

from eval.judge import check_citations

SOURCES = [
    {"n": 1, "title": "Kalman Filter", "text": "..."},
    {"n": 2, "title": "Hungarian Algorithm", "text": "..."},
]


def test_every_citation_resolves():
    result = check_citations("Predict then update [1]. Then assign [2].", SOURCES)
    assert result == {"cited": [1, 2], "dangling": [], "valid": True, "uncited_sources": 0}


def test_citation_to_a_source_that_was_never_returned():
    # The failure that matters: a plausible-looking [3] with nothing behind it.
    result = check_citations("The gate is 9.4877 [3].", SOURCES)
    assert result["valid"] is False
    assert result["dangling"] == [3]


def test_uncited_sources_are_counted_not_penalised():
    result = check_citations("Predict then update [1].", SOURCES)
    assert result["valid"] is True
    assert result["uncited_sources"] == 1


def test_repeated_citation_counted_once():
    result = check_citations("One [1]. Two [1]. Three [1].", SOURCES)
    assert result["cited"] == [1]


def test_answer_with_no_citations_at_all():
    result = check_citations("I could not find this in the knowledge base.", SOURCES)
    assert result == {"cited": [], "dangling": [], "valid": True, "uncited_sources": 2}


def test_bracketed_numbers_that_are_not_citations_still_count():
    # A known limitation, pinned so it is a decision rather than a surprise:
    # the regex cannot tell a citation from an array index in a code snippet.
    assert check_citations("Use boxes[0] and boxes[1].", SOURCES)["cited"] == [0, 1]
