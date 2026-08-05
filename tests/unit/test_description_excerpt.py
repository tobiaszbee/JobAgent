from collector.utils import strip_description_junk, build_excerpt, excerpt_looks_incomplete


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
        # Real content is short, but total (incl. junk) exceeds the cap, the cap
        # must apply to the cleaned text, not silently include junk up to 6000 chars.
        desc = "Real content." + "\n\nSet alert for similar jobs\n\n" + ("y" * 10000)
        result = build_excerpt(desc, "linkedin")
        assert result == "Real content."

    def test_linkedin_caps_at_8000_not_6000(self):
        # Regression: a sample of 100 recent LinkedIn postings found 20% still over
        # 6000 chars even after junk-stripping, real content (once, an entire
        # "Benefits found in job post" section) silently cut, not junk. LinkedIn's
        # own fetch_description() never returns more than 8000 chars to begin with
        # (collector/sources/linkedin.py), so capping here at 8000 instead just stops
        # re-trimming what was already fetched.
        desc = "x" * 10000
        result = build_excerpt(desc, "linkedin")
        assert len(result) == 8000

    def test_non_linkedin_source_still_caps_at_6000(self):
        desc = "x" * 10000
        result = build_excerpt(desc, "justjoin")
        assert len(result) == 6000


class TestExcerptLooksIncomplete:
    def test_empty_excerpt_is_not_incomplete(self):
        # A missing description is a different, already-handled case (build_excerpt
        # already returns "" for it), not this function's concern.
        assert excerpt_looks_incomplete("") is False

    def test_short_excerpt_is_incomplete(self):
        # itpracuj's search-result preview (its only description source) measured
        # 113-250 chars in practice.
        assert excerpt_looks_incomplete("x" * 200) is True

    def test_excerpt_at_threshold_is_not_incomplete(self):
        assert excerpt_looks_incomplete("x" * 400) is False

    def test_excerpt_just_under_threshold_is_incomplete(self):
        assert excerpt_looks_incomplete("x" * 399) is True

    def test_long_excerpt_is_not_incomplete(self):
        assert excerpt_looks_incomplete("x" * 3000) is False
