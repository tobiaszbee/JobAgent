from config import STEALTH
from collector.sources.linkedin import _reading_seconds


class TestReadingSeconds:
    def test_short_text_clamped_to_min(self):
        for _ in range(50):
            seconds = _reading_seconds("just a few words here")
            assert seconds == STEALTH["desc_delay_min"]

    def test_long_text_clamped_to_max(self):
        long_text = "word " * 5000
        for _ in range(50):
            seconds = _reading_seconds(long_text)
            assert seconds == STEALTH["desc_delay_max"]

    def test_longer_text_reads_longer_on_average(self):
        short_text = "word " * 50
        long_text = "word " * 300
        short_avg = sum(_reading_seconds(short_text) for _ in range(100)) / 100
        long_avg = sum(_reading_seconds(long_text) for _ in range(100)) / 100
        assert long_avg > short_avg

    def test_within_configured_bounds(self):
        mid_text = "word " * 150
        for _ in range(100):
            seconds = _reading_seconds(mid_text)
            assert STEALTH["desc_delay_min"] <= seconds <= STEALTH["desc_delay_max"]
