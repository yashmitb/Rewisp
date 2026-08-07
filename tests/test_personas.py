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


class TestFilingFilesIsSafe:
    """apply_split MOVES the user's identity documents. It had no tests at all."""

    def test_a_persona_name_cannot_escape_the_vault(self, conn, vault_dir, tmp_path):
        # The one that mattered: '../../../tmp/evil' resolved outside the Vault
        # entirely, so approving a split could have relocated identity documents
        # anywhere the user could write.
        vault_dir("info.md", "Email: me@gmail.com")
        outside = tmp_path / "evil"
        res = personas.apply_split(conn, [{"path": "info.md", "persona": "../../evil"}])
        assert not outside.exists()
        assert (config.VAULT_DIR / "info.md").exists() or res["moved"]
        for moved in res["moved"]:
            assert (config.VAULT_DIR / moved).resolve().is_relative_to(
                config.VAULT_DIR.resolve())

    def test_an_absolute_persona_name_is_neutered(self, conn, vault_dir):
        vault_dir("info.md", "Email: me@gmail.com")
        personas.apply_split(conn, [{"path": "/etc/passwd", "persona": "personal"}])
        assert not (config.VAULT_DIR / "personal" / "passwd").exists()

    def test_a_path_outside_the_vault_is_refused(self, conn, vault_dir):
        vault_dir("info.md", "x")
        res = personas.apply_split(conn, [{"path": "../../secrets.md", "persona": "work"}])
        assert res["moved"] == []

    def test_an_approved_file_is_moved_and_reindexed(self, conn, vault_dir):
        vault_dir("info.md", "Email: me@ucsd.edu")
        res = personas.apply_split(conn, [{"path": "info.md", "persona": "school"}])
        assert res["moved"] == ["school/info.md"]
        assert (config.VAULT_DIR / "school" / "info.md").is_file()
        assert not (config.VAULT_DIR / "info.md").exists()
        # The index keys on path, so a move that isn't reindexed keeps answering
        # as a shared file.
        paths = [p for (p,) in conn.execute("SELECT path FROM vault_files")]
        assert "school/info.md" in paths and "info.md" not in paths

    def test_only_approved_files_move(self, conn, vault_dir):
        vault_dir("a.md", "Email: me@ucsd.edu")
        vault_dir("b.md", "Email: me@gmail.com")
        personas.apply_split(conn, [{"path": "a.md", "persona": "school"}])
        assert (config.VAULT_DIR / "b.md").is_file()

    def test_an_already_filed_file_is_left_alone(self, conn, vault_dir):
        vault_dir("school/info.md", "Email: me@ucsd.edu")
        res = personas.apply_split(conn, [{"path": "school/info.md", "persona": "work"}])
        assert res["moved"] == []
        assert (config.VAULT_DIR / "school" / "info.md").is_file()

    def test_a_name_collision_fails_rather_than_overwriting(self, conn, vault_dir):
        vault_dir("school/info.md", "Email: school@ucsd.edu")
        vault_dir("info.md", "Email: other@gmail.com")
        res = personas.apply_split(conn, [{"path": "info.md", "persona": "school"}])
        assert res["failed"] == ["info.md"]
        assert (config.VAULT_DIR / "school" / "info.md").read_text().startswith("Email: school@")

    def test_empty_persona_name_is_ignored(self, conn, vault_dir):
        vault_dir("info.md", "x")
        assert personas.apply_split(conn, [{"path": "info.md", "persona": "   "}])["moved"] == []

    def test_ensure_folders_only_creates_safe_names(self, conn, vault_dir):
        vault_dir("info.md", "x")
        made = personas.ensure_folders(conn, ["school", "../escape", "Work"])
        assert "school" in made and "work" in made
        assert (config.VAULT_DIR / "school").is_dir()
        for d in config.VAULT_DIR.iterdir():
            assert d.resolve().parent == config.VAULT_DIR.resolve()


class TestHonestLabelling:
    def test_a_shared_value_is_labelled_shared_not_a_persona(self, conn, vault_dir):
        # A phone in a top-level file belongs to everyone. Crediting it to
        # whichever persona sorted first was the bug: the label flipped with the
        # ordering, and both answers were wrong.
        vault_dir("shared.md", "Phone: (555) 123-4567")
        vault_dir("school/info.md", "Email: me@ucsd.edu")
        vals = personas.values_for(conn, "what is my phone number")
        assert len(vals) == 1
        assert vals[0]["shared"] is True
        assert vals[0]["persona"] is None

    def test_a_persona_value_is_not_marked_shared(self, vaulted):
        vals = personas.values_for(vaulted, "what is my email")
        assert all(v["shared"] is False for v in vals if v["persona"])

    def test_a_persona_without_its_own_value_does_not_claim_the_shared_one(self, conn, vault_dir):
        vault_dir("shared.md", "Email: everyone@example.com")
        vault_dir("school/info.md", "Student ID: A1829")
        vals = personas.values_for(conn, "what is my email")
        assert [v["persona"] for v in vals] == [None]


class TestProposalRefusesToGuess:
    def test_an_ambiguous_file_gets_no_suggestion(self, conn, vault_dir):
        # Both a .edu and a Gmail: genuinely could be either, so picking one by
        # dict order would be a coin flip presented as advice.
        vault_dir("info.md", "School: me@ucsd.edu\nPersonal: me@gmail.com")
        assert personas.propose_split(conn) == []

    def test_a_passing_mention_of_the_project_is_not_an_identity(self, conn, vault_dir):
        vault_dir("portfolio.md", "Projects: Rewisp, an ambient memory for macOS")
        assert personas.propose_split(conn) == []

    def test_lunar_client_is_not_freelance_work(self, conn, vault_dir):
        vault_dir("games.md", "Lunar Client settings and keybinds")
        assert personas.propose_split(conn) == []


class TestEdges:
    def test_known_personas_with_nothing_to_read(self):
        assert personas.known_personas() == []

    def test_an_empty_vault_answers_nothing(self, conn, vault_dir):
        vault_dir("empty.md", "nothing useful here")
        assert personas.values_for(conn, "what is my email") == []

    def test_nested_folders_belong_to_the_top_persona(self):
        assert personas.persona_of("work/clients/acme/info.md") == "work"


class TestSharedDocumentsStaySharedd:
    """Caught by a dry run on a real Vault, not by any unit test."""

    def test_a_resume_is_not_filed_under_the_address_printed_on_it(self, conn, vault_dir):
        vault_dir("Yashmit_s_College_Resume.md",
                  "Yashmit Bhaverisetti\nybhaverisetti@ucsd.edu\nExperience: ...")
        assert personas.propose_split(conn) == []

    def test_transcript_portfolio_and_links_stay_shared(self, conn, vault_dir):
        for name in ("latestcollegetrans.md", "my_portfolio.md", "bhaverisetti_links.md"):
            vault_dir(name, "UCSD transcript\nybhaverisetti@ucsd.edu")
        assert personas.propose_split(conn) == []

    def test_an_actual_contact_file_is_still_proposed(self, conn, vault_dir):
        # The guard must not swallow the files personas are actually for.
        vault_dir("school_info.md", "Email: me@ucsd.edu\nStudent ID: A1829")
        s = personas.propose_split(conn)
        assert len(s) == 1 and s[0]["suggested"] == "school"


class TestSplittingOneFileWithSeveralIdentities:
    """The case the per-file model cannot express, and the one that matters:
    a single 'personal info' note holding a student id, a university address
    and a personal address."""

    def test_a_multi_identity_note_is_offered_for_splitting(self, conn, vault_dir):
        vault_dir("info.md", "Name: A Person\nUCSD PID: A1829\n"
                             "Personal email address: me@gmail.com\n"
                             "UCSD school email address: me@ucsd.edu\n"
                             "Phone number: 5551234567\n")
        props = personas.propose_line_split(conn)
        assert len(props) == 1
        assert props[0]["personas"] == ["personal", "school"]

    def test_a_single_identity_note_is_not(self, conn, vault_dir):
        vault_dir("info.md", "Personal email address: me@gmail.com\nPhone: 5551234567\n")
        assert personas.propose_line_split(conn) == []

    def test_a_long_document_is_never_shredded(self, conn, vault_dir):
        # A 90-line portfolio was being chopped line by line into persona
        # folders. A long document is a document, not a list of identity facts.
        body = "\n".join(["Personal project number %d" % i for i in range(40)]
                         + ["UCSD school email address: me@ucsd.edu"])
        vault_dir("notes.md", body)
        assert personas.propose_line_split(conn) == []

    def test_a_resume_is_never_split(self, conn, vault_dir):
        vault_dir("my_resume.md", "Personal email address: me@gmail.com\n"
                                  "UCSD school email address: me@ucsd.edu\n")
        assert personas.propose_line_split(conn) == []

    def test_splitting_writes_each_persona_its_own_file(self, conn, vault_dir):
        vault_dir("info.md", "Name: A Person\nUCSD PID: A1829\n"
                             "Personal email address: me@gmail.com\n"
                             "UCSD school email address: me@ucsd.edu\n")
        p = personas.propose_line_split(conn)[0]
        res = personas.apply_line_split(conn, "info.md", p["lines"])
        assert sorted(res["written"]) == ["personal/info.md", "school/info.md"]
        assert "me@ucsd.edu" in (config.VAULT_DIR / "school" / "info.md").read_text()
        assert "me@gmail.com" in (config.VAULT_DIR / "personal" / "info.md").read_text()
        # The shared line stays shared.
        assert "A Person" in (config.VAULT_DIR / "info.md").read_text()

    def test_the_original_is_always_recoverable(self, conn, vault_dir):
        vault_dir("info.md", "UCSD PID: A1829\nPersonal email address: me@gmail.com\n")
        p = personas.propose_line_split(conn)[0]
        res = personas.apply_line_split(conn, "info.md", p["lines"])
        backup = config.VAULT_DIR / res["backup"]
        assert backup.is_file() and "A1829" in backup.read_text()
        # Dot-prefixed, so reindex ignores it and the values are not duplicated.
        assert res["backup"].startswith(".")
        paths = [x for (x,) in conn.execute("SELECT path FROM vault_files")]
        assert not any(x.startswith(".") for x in paths)

    def test_a_non_text_document_is_never_overwritten_with_text(self, conn, vault_dir, tmp_path):
        # The bug that destroyed a 2-page PDF in a sandbox run: for anything but
        # plain text the indexed content is EXTRACTED text, so writing it back
        # replaces the document with a transcript of itself.
        rtf = config.VAULT_DIR / "info.rtf"
        rtf.write_text("Personal email address: me@gmail.com\n"
                       "UCSD school email address: me@ucsd.edu\n")
        original = rtf.read_bytes()
        vault.reindex(conn)
        props = [p for p in personas.propose_line_split(conn) if p["path"] == "info.rtf"]
        if props:
            personas.apply_line_split(conn, "info.rtf", props[0]["lines"])
            # Either untouched, or retired to the backup with its bytes intact.
            if rtf.exists():
                assert rtf.read_bytes() == original
            else:
                assert (config.VAULT_DIR / ".info.rtf.before-split").read_bytes() == original


class TestFactKindsDoNotCross:
    def test_asking_for_an_address_never_returns_an_email(self, conn, vault_dir):
        # "address" is a substring of "email address", so the postal lookup
        # answered with a .edu address on real data.
        vault_dir("personal/info.md", "UCSD school email address: me@ucsd.edu\n"
                                      "Home address: 1 Main St, Springfield\n")
        vals = personas.values_for(conn, "what is my address")
        assert vals and "@" not in vals[0]["answer"]

    def test_a_two_word_question_needs_two_word_agreement(self, conn, vault_dir):
        vault_dir("school/info.md", "UCSD PID: A1829\n")
        vault_dir("other.md", "Github: someone |someone.me\n")
        vals = personas.values_for(conn, "what is my ucsd pid")
        assert [v["answer"] for v in vals] == ["A1829"]
