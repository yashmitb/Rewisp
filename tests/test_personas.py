"""Personas — which *you* a value belongs to.

The rules worth pinning are the safety ones. Filling the wrong identity into a
form is the failure that would make the feature untrustworthy, so: a site never
seen before must return None (meaning "offer", never "guess"), a persona's own
answer must beat the shared one, and nothing may move a file on disk without
being asked.
"""

import pytest

from rewisp import config, personas, vault


@pytest.fixture
def vault_dir(conn, tmp_path, monkeypatch):
    """A real Vault on disk, indexed the real way.

    Deliberately not hand-written rows in vault_files: `reindex` deletes rows
    whose file is gone, so invented rows vanish the moment anything reindexes —
    which is what the first version of these tests did, and it hid behind a
    passing assertion until the code under test started reindexing too. Real
    files also prove the thing the whole design rests on: that a subfolder
    survives reindex as part of the stored path.
    """
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(config, "VAULT_DIR", root)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn.executescript(vault.VAULT_SCHEMA)

    def write(rel, content):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        vault.reindex(conn)
    return write


@pytest.fixture
def vaulted(conn, vault_dir):
    """Two personas and one shared file."""
    vault_dir("school/info.md", "Email: ybhaverisetti@ucsd.edu\nStudent ID: A18294\n")
    vault_dir("personal/info.md", "Email: yashmitb07@gmail.com\nPhone: (555) 123-4567\n")
    vault_dir("resume.md", "Yashmit Bhaverisetti — resume\nPhone: (555) 123-4567\n")
    return conn


class TestOwnership:
    def test_a_subfolder_is_a_persona(self):
        assert personas.persona_of("school/info.md") == "school"
        assert personas.persona_of("work/nested/deep.md") == "work"

    def test_a_top_level_file_belongs_to_everyone(self):
        # Your transcript does not become school-only just because school exists.
        assert personas.persona_of("resume.md") is None

    def test_only_personas_with_files_exist(self, vaulted):
        found = personas.known_personas(vaulted)
        assert set(found) == {"school", "personal"}

    def test_primary_is_listed_first(self, vaulted):
        assert personas.known_personas(vaulted)[0] == "personal"


class TestAnswering:
    def test_each_persona_answers_with_its_own_value(self, vaulted):
        vals = personas.values_for(vaulted, "what is my email")
        by = {v["persona"]: v["answer"] for v in vals}
        assert by["school"] == "ybhaverisetti@ucsd.edu"
        assert by["personal"] == "yashmitb07@gmail.com"

    def test_primary_leads_so_copy_is_predictable(self, vaulted):
        assert personas.values_for(vaulted, "what is my email")[0]["persona"] == "personal"

    def test_a_shared_value_is_listed_once_not_per_persona(self, vaulted):
        # The phone lives in a shared file and in personal/. It is one fact, and
        # repeating it per persona would be noise pretending to be a choice.
        vals = personas.values_for(vaulted, "what is my phone number")
        assert len({v["answer"] for v in vals}) == len(vals)

    def test_a_persona_beats_the_shared_file(self, conn, vault_dir):
        vault_dir("info.md", "Email: shared@example.com")
        vault_dir("work/info.md", "Email: me@acme.com")
        vals = {v["persona"]: v["answer"] for v in personas.values_for(conn, "what is my email")}
        assert vals["work"] == "me@acme.com"


class TestSiteMemory:
    def test_an_unseen_site_returns_none_so_the_ui_must_offer(self, conn):
        # The whole safety argument. None means ask; it must never fall back to
        # a guess that gets filled in silently.
        assert personas.for_site(conn, "https://example.com/signup") is None

    def test_a_choice_is_remembered_for_the_site(self, conn):
        personas.remember_site(conn, "https://www.amazon.com/checkout", "personal")
        assert personas.for_site(conn, "https://amazon.com/gp/cart") == "personal"

    def test_memory_is_per_host_not_per_page(self, conn):
        personas.remember_site(conn, "https://amazon.com/a?x=1", "personal")
        assert personas.for_site(conn, "https://amazon.com/completely/other") == "personal"

    def test_changing_the_choice_overwrites_it(self, conn):
        personas.remember_site(conn, "https://slack.com", "personal")
        personas.remember_site(conn, "https://slack.com", "work")
        assert personas.for_site(conn, "https://slack.com") == "work"

    def test_native_apps_are_keyed_by_app_name(self, conn):
        personas.remember_site(conn, None, "work", app="Mail")
        assert personas.for_site(conn, None, app="Mail") == "work"

    def test_a_site_can_be_forgotten(self, conn):
        personas.remember_site(conn, "https://example.com", "work")
        assert personas.forget_site(conn, "https://example.com")
        assert personas.for_site(conn, "https://example.com") is None

    def test_no_url_and_no_app_is_not_remembered(self, conn):
        assert personas.remember_site(conn, None, "work") == ""
        assert personas.for_site(conn, None) is None


class TestProposedSplit:
    def test_an_edu_address_suggests_school(self, conn, vault_dir):
        vault_dir("info.md", "Email: me@ucsd.edu")
        s = personas.propose_split(conn)
        assert s[0]["suggested"] == "school"
        assert s[0]["evidence"]                    # it shows what convinced it

    def test_a_consumer_address_suggests_personal(self, conn, vault_dir):
        vault_dir("info.md", "Email: me@gmail.com")
        assert personas.propose_split(conn)[0]["suggested"] == "personal"

    def test_already_filed_files_are_left_alone(self, vaulted):
        assert all(p["path"] == "resume.md" for p in personas.propose_split(vaulted))

    def test_a_file_with_no_signal_is_not_guessed_at(self, conn, vault_dir):
        # Silence is the correct output. A wrong guess files an identity document
        # under the wrong person and then answers from it forever.
        vault_dir("notes.md", "Remember to water the plants")
        assert personas.propose_split(conn) == []
