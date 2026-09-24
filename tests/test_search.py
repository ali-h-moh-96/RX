from __future__ import annotations

from types import SimpleNamespace

from prescription_archive.pages.search import SearchMixin


class DummyEntry:
    def __init__(self):
        self.value = ""

    def delete(self, start, end):
        self.value = ""

    def get(self):
        return self.value


class DummyCombo:
    def set(self, value):
        self.value = value


class DummyBooleanVar:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = bool(value)


class DummySearch(SearchMixin):
    def __init__(self):
        self.s_meds = DummyEntry()
        self.s_people = DummyEntry()
        self.s_category = DummyCombo()
        self.s_date_from = DummyEntry()
        self.s_date_to = DummyEntry()
        self.s_or_mode = DummyBooleanVar(True)
        self._refresh_search_called = 0

    def _refresh_search(self):
        self._refresh_search_called += 1


def test_search_show_all_resets_or_mode_and_filters():
    search = DummySearch()
    search.s_meds.value = "amoxicillin, ibuprofen"
    search.s_people.value = "Dr. Smith"
    search.s_category.value = "Cardiology"
    search.s_date_from.value = "2024-01-01"
    search.s_date_to.value = "2024-05-01"

    search._search_show_all()

    assert search.s_or_mode.get() is False
    assert search.s_meds.get() == ""
    assert search.s_people.get() == ""
    assert search.s_category.value == "Any"
    assert search.s_date_from.get() == ""
    assert search.s_date_to.get() == ""
    assert search._refresh_search_called == 1
