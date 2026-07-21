from config import STEALTH
from collector.runner import _search_pause_seconds


class TestSearchPauseSeconds:
    def test_zero_new_stays_within_glance_range(self):
        for _ in range(50):
            pause = _search_pause_seconds(0)
            assert STEALTH["search_glance_min"] <= pause <= STEALTH["search_glance_max"]

    def test_new_jobs_add_reading_time_on_top_of_glance(self):
        for _ in range(50):
            pause = _search_pause_seconds(5)
            lower = STEALTH["search_glance_min"] + 5 * STEALTH["search_new_min"]
            upper = STEALTH["search_glance_max"] + 5 * STEALTH["search_new_max"]
            assert lower <= pause <= upper

    def test_more_new_jobs_means_longer_expected_pause(self):
        few = sum(_search_pause_seconds(1) for _ in range(200)) / 200
        many = sum(_search_pause_seconds(10) for _ in range(200)) / 200
        assert many > few
