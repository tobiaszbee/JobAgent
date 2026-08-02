from collector.location import workplace_suffix


class TestWorkplaceSuffix:
    def test_remote_only(self):
        assert workplace_suffix({"remote"}) == " (Remote)"

    def test_hybrid_only(self):
        assert workplace_suffix({"hybrid"}) == " (Hybrid)"

    def test_onsite_only_has_no_suffix(self):
        assert workplace_suffix({"onsite"}) == ""

    def test_empty_set_has_no_suffix(self):
        assert workplace_suffix(set()) == ""

    def test_remote_wins_over_hybrid_when_both_present(self):
        assert workplace_suffix({"remote", "hybrid"}) == " (Remote)"

    def test_hybrid_wins_over_onsite_when_both_present(self):
        assert workplace_suffix({"hybrid", "onsite"}) == " (Hybrid)"
