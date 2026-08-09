"""Autofill, told which *you* it is filling as.

This is the half of the persona feature that matters. Everything else — the
folders, the split, the settings pane — exists so that this moment is right: the
box on the page gets the .edu on a course site and the Gmail on a shopping cart,
and on a site nobody has seen before it gets NOTHING until the user says which.

The rule under test is the refusal. A silently wrong identity in a submitted
form is the failure that would make nobody trust the feature again, so a form on
an unsettled site must not fill, however confident the Vault is.
"""

import pytest

from rewisp import config, form, personas, server, vault


@pytest.fixture
def vault_dir(conn, tmp_path, monkeypatch):
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
def two_identities(conn, vault_dir):
    vault_dir("school/info.md", "Email: ybhaverisetti@ucsd.edu\n")
    vault_dir("personal/info.md", "Email: yashmitb07@gmail.com\n")
    vault_dir("shared.md", "Phone: (555) 123-4567\n")
    return conn


class TestFillingAsSomeone:
    def test_each_persona_fills_its_own_address(self, two_identities):
        conn = two_identities
        school = form.resolve(conn, ["Email"], "school")[0]["value"]
        personal = form.resolve(conn, ["Email"], "personal")[0]["value"]
        assert school.endswith(".edu")
        assert personal.endswith("@gmail.com")

    def test_a_shared_value_still_answers_for_every_persona(self, two_identities):
        # A phone number that belongs to everybody must not disappear just
        # because the form is being filled as one identity.
        for who in ("school", "personal"):
            v = form.resolve(two_identities, ["Phone"], who)[0]["value"]
            assert v and "555" in v, who

    def test_no_persona_means_the_whole_vault_as_before(self, conn, vault_dir):
        # A Vault with no personas in it behaves exactly as it always did.
        vault_dir("info.md", "Email: solo@example.com\n")
        assert form.resolve(conn, ["Email"])[0]["value"] == "solo@example.com"

    def test_a_password_field_is_still_refused_whoever_is_filling(self, two_identities):
        r = form.resolve(two_identities, ["Password", "Card number"], "school")
        assert [f["found"] for f in r] == [False, False]


class TestTheRefusal:
    """`_persona_for_form` is the single place the safety order lives, so both
    /form-fill and /form-write cannot drift apart about it."""

    def test_an_unsettled_site_is_not_settled_and_offers_everyone(self, two_identities):
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["settled"] is False
        assert who["persona"] is None            # None means OFFER
        assert {c["name"] for c in who["choices"]} == {"school", "personal"}

    def test_an_unsettled_site_previews_the_primary_rather_than_a_mixture(
            self, two_identities):
        # Resolving against the whole Vault would answer from whichever identity
        # matched first — the silent mixing this feature exists to end.
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["showing"] == personas.primary()

    def test_an_explicit_pick_wins_and_is_what_gets_filled(self, two_identities):
        who = server._persona_for_form(two_identities, "Safari", {"persona": "school"})
        assert who["persona"] == "school"
        assert form.resolve(two_identities, ["Email"],
                            who["persona"])[0]["value"].endswith(".edu")

    def test_a_settled_site_needs_no_asking(self, two_identities):
        personas.remember_site(two_identities, None, "school", app="Mail")
        who = server._persona_for_form(two_identities, "Mail", {})
        assert who["settled"] is True and who["persona"] == "school"

    def test_a_pick_that_is_not_a_real_persona_is_ignored(self, two_identities):
        # clean_name would turn this into "etc" — harmless, meaningless, and
        # capable of settling a site on an identity with nothing behind it.
        who = server._persona_for_form(two_identities, "Safari",
                                       {"persona": "../../etc"})
        assert who["persona"] is None

    def test_one_identity_is_never_a_question(self, conn, vault_dir):
        # Nothing to disambiguate: no chips, and no refusal to fill.
        vault_dir("personal/info.md", "Email: me@gmail.com\n")
        who = server._persona_for_form(conn, "Safari", {})
        assert len(who["choices"]) == 1
