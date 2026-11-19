"""Dates written inside a document: what counts, what is left out."""

from __future__ import annotations

from datetime import date

from sextant.vector_db.dates import dates_in, newest

TODAY = date(2026, 11, 19)


def found(text: str) -> list[str]:
    return [d.isoformat() for d in dates_in(text, TODAY)]


class TestWrittenForms:
    def test_day_first_with_any_separator(self):
        assert found("Bill date 12/03/2024, read on 05-04-2024 and 06.04.2024") == [
            "2024-03-12", "2024-04-05", "2024-04-06"]

    def test_month_first_only_when_the_middle_cannot_be_a_month(self):
        assert found("issued 03/25/2024") == ["2024-03-25"]

    def test_year_first(self):
        assert found("generated 2023-07-01") == ["2023-07-01"]

    def test_month_names_long_short_and_ordinal(self):
        assert found("1st Sept 2021; March 3, 2022; 14-Feb-2020") == [
            "2020-02-14", "2021-09-01", "2022-03-03"]

    def test_a_month_and_year_count_from_the_first(self):
        assert found("Statement for March 2024") == ["2024-03-01"]

    def test_devanagari_numerals(self):
        assert found("दिनांक १२/०३/२०२४") == ["2024-03-12"]


class TestWhatIsLeftOut:
    def test_future_dates_are_due_or_expiry_dates(self):
        assert found("Issued 10/01/2019. Valid till 09/01/2029") == ["2019-01-10"]

    def test_impossible_dates_and_bare_numbers(self):
        assert found("31/02/2024, 2008 / 600, 1234 5678 9012, 45/45/2020") == []

    def test_a_word_that_starts_like_a_month_is_not_one(self):
        assert found("marks 2008, decide 2010, junior 2015") == []

    def test_each_date_once(self):
        assert found("12/03/2024 and again 12 March 2024") == ["2024-03-12"]


class TestNewest:
    def test_newest_across_a_documents_passages(self):
        assert newest(["Born 01/01/1990", "Bill date 12/03/2024"], TODAY) == date(2024, 3, 12)

    def test_none_when_nothing_is_dated(self):
        assert newest(["no dates here"], TODAY) is None
