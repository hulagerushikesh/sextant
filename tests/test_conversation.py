"""Bounding a client-supplied transcript.

Everything here is about untrusted input: the transcript arrives from a browser
tab that may be stale, half-finished, or reordered, and none of those should
cost the user their answer.
"""

from __future__ import annotations

from mcp_server.conversation import MAX_CHARS, MAX_TURN_CHARS, MAX_TURNS, replay


def exchange(n: int) -> list[dict[str, str]]:
    return [
        item
        for i in range(n)
        for item in (
            {"role": "user", "content": f"q{i}"},
            {"role": "assistant", "content": f"a{i}"},
        )
    ]


class TestShape:
    def test_a_clean_transcript_passes_through(self):
        assert replay(exchange(2)) == [
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

    def test_nothing_in_nothing_out(self):
        assert replay([]) == []

    def test_a_trailing_question_is_dropped(self):
        # The previous request never completed -- an aborted stream, or a tab
        # closed mid-answer. Sending it would ask the model two questions.
        assert replay(exchange(1) + [{"role": "user", "content": "orphan"}]) == exchange(1)

    def test_a_leading_answer_is_dropped(self):
        assert replay([{"role": "assistant", "content": "a"}, *exchange(1)]) == exchange(1)

    def test_two_questions_in_a_row_keep_the_newer(self):
        history = [
            {"role": "user", "content": "first try"},
            {"role": "user", "content": "rephrased"},
            {"role": "assistant", "content": "answer"},
        ]
        assert [t["content"] for t in replay(history)] == ["rephrased", "answer"]

    def test_blank_and_unknown_roles_are_ignored(self):
        history = [
            {"role": "system", "content": "ignore me"},
            {"role": "user", "content": "   "},
            *exchange(1),
        ]
        assert replay(history) == exchange(1)

    def test_the_result_always_alternates(self):
        messy = [
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]
        roles = [turn["role"] for turn in replay(messy)]
        assert roles == ["user", "assistant"]


class TestBounds:
    def test_only_the_most_recent_turns_survive(self):
        replayed = replay(exchange(MAX_TURNS))
        assert len(replayed) == MAX_TURNS
        assert replayed[0]["content"] == f"q{MAX_TURNS // 2}"

    def test_a_long_turn_is_clipped_from_the_front(self):
        # The end of an answer is the part a follow-up refers to.
        long_answer = "start" + "y" * (MAX_TURN_CHARS * 2) + "END"
        replayed = replay(
            [{"role": "user", "content": "q"}, {"role": "assistant", "content": long_answer}]
        )
        assert replayed[1]["content"].endswith("END")
        assert "start" not in replayed[1]["content"]
        assert len(replayed[1]["content"]) <= MAX_TURN_CHARS + 2

    def test_the_character_budget_trims_in_pairs(self):
        heavy = [
            item
            for i in range(6)
            for item in (
                {"role": "user", "content": f"q{i}"},
                {"role": "assistant", "content": "z" * (MAX_CHARS // 4)},
            )
        ]
        replayed = replay(heavy)
        assert sum(len(t["content"]) for t in replayed) <= MAX_CHARS
        # Still a conversation, not a fragment starting mid-answer.
        assert replayed[0]["role"] == "user"
        assert len(replayed) % 2 == 0
