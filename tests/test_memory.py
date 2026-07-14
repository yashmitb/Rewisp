"""Memory fuzzy de-dupe — stop the digest re-proposing facts it already learned."""
from rewisp import memory


class TestSimilar:
    def test_reworded_same_fact(self):
        assert memory._similar(
            "Data Science student at UC San Diego, open to Summer 2027 internships",
            "Data Science student at UC San Diego; portfolio states open to Summer 2027 internships")

    def test_plural_and_punctuation_variants(self):
        assert memory._similar("Scouting volunteer (Troop 511/2511)",
                               "He volunteers with Scouting Troop 511/2511")

    def test_distinct_facts_not_merged(self):
        assert not memory._similar("Prefers short answers", "Prioritizing robotics internships")
        assert not memory._similar("Uses Claude Pro", "Uses Gemini as fallback")
        assert not memory._similar("Studies late at night", "Prefers dark mode")
