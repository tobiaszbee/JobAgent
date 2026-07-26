from collector.utils import strip_description_junk, build_excerpt


class TestStripDescriptionJunk:
    def test_cuts_at_set_alert_marker_for_linkedin(self):
        desc = "Real job content here.\n\nSet alert for similar jobs\n\nFooter junk galore."
        result = strip_description_junk(desc, "linkedin")
        assert result == "Real job content here."
        assert "Set alert" not in result

    def test_cuts_at_earliest_marker_when_multiple_present(self):
        desc = "Content.\n\nAccessibility\n\nmore junk\n\nSet alert for similar jobs\n\neven more"
        result = strip_description_junk(desc, "linkedin")
        assert result == "Content."

    def test_no_marker_present_returns_unchanged(self):
        desc = "A perfectly normal job description with no junk markers at all."
        assert strip_description_junk(desc, "linkedin") == desc

    def test_non_linkedin_source_passes_through_unchanged(self):
        desc = "Some description that happens to mention Accessibility as a requirement."
        assert strip_description_junk(desc, "justjoin") == desc

    def test_none_source_passes_through_unchanged(self):
        desc = "Some description mentioning Accessibility."
        assert strip_description_junk(desc, None) == desc

    def test_empty_description_returns_empty(self):
        assert strip_description_junk("", "linkedin") == ""


class TestBuildExcerpt:
    def test_none_description_returns_empty_string(self):
        assert build_excerpt(None, "linkedin") == ""

    def test_strips_linkedin_junk(self):
        desc = "Great job.\n\nSet alert for similar jobs\n\njunk"
        assert build_excerpt(desc, "linkedin") == "Great job."

    def test_caps_at_6000_chars(self):
        desc = "x" * 10000
        result = build_excerpt(desc, "justjoin")
        assert len(result) == 6000

    def test_under_cap_stays_full_length(self):
        desc = "x" * 5000
        result = build_excerpt(desc, "justjoin")
        assert len(result) == 5000

    def test_junk_stripped_before_cap_applied(self):
        # Real content is short, but total (incl. junk) exceeds the cap — the cap
        # must apply to the cleaned text, not silently include junk up to 6000 chars.
        desc = "Real content." + "\n\nSet alert for similar jobs\n\n" + ("y" * 10000)
        result = build_excerpt(desc, "linkedin")
        assert result == "Real content."
