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


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """Never let a test reach the real AppleScript bridge.

    Tests naming "Safari" were quietly spawning osascript against whatever
    Safari was actually doing — slow, machine-dependent, and up to a 3s timeout
    each. Tests that care about browser behaviour override this themselves.
    """
    from rewisp import browser
    monkeypatch.setattr(browser, "is_browser", lambda app: False)
    monkeypatch.setattr(browser, "active_tab", lambda app: (None, None, False))


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


class TestPreviewIsNotAPick:
    """The panel previews an identity before the user has chosen one. Shipping
    that preview back as `persona` made the daemon treat it as an answer — the
    site filled with the primary and settled itself, which is precisely what the
    refusal is for. The server contract has to make the two states distinct."""

    def test_no_persona_in_the_body_leaves_the_site_unsettled(self, two_identities):
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["persona"] is None          # -> the caller must 409
        assert who["showing"] is not None      # ...while still previewing

    def test_only_an_explicit_pick_settles_the_site(self, two_identities):
        # Keyed on a native app, which is the case where the app IS the unit.
        conn = two_identities
        # A preview alone must never reach remember_site.
        assert personas.for_site(conn, None, "Mail") is None
        who = server._persona_for_form(conn, "Mail", {"persona": "school"})
        assert who["remember"] is True
        personas.remember_site(conn, who.get("url"), who["persona"], "Mail")
        after = server._persona_for_form(conn, "Mail", {})
        assert after["settled"] is True and after["persona"] == "school"


class TestFindingTheAppWithoutWalkingAccessibility:
    """/form-write needs the app name only to pick an identity; the fill is
    already a deep AX walk. Asking for it made every fill walk twice."""

    def test_the_body_is_believed_first(self):
        assert server._form_app(123, {"app": "Safari"}) == "Safari"

    def test_the_daemon_cache_answers_for_the_same_pid(self, monkeypatch):
        import time
        from rewisp import daemon
        monkeypatch.setitem(daemon.STATE, "frontmost",
                            {"app": "Google Chrome", "pid": 777, "ts": time.time()})
        assert server._form_app(777, {}) == "Google Chrome"

    def test_a_stale_or_mismatched_cache_is_not_used(self, monkeypatch):
        import time
        from rewisp import daemon, form
        monkeypatch.setitem(daemon.STATE, "frontmost",
                            {"app": "Google Chrome", "pid": 999, "ts": time.time() - 600})
        called = []
        monkeypatch.setattr(form, "query", lambda pid: called.append(pid) or None)
        assert server._form_app(777, {}) is None
        assert called == [777]          # fell through to the real walk


class TestWhereAChoiceMayBeRemembered:
    """Settling a site writes its address down. The kill list and private
    windows are promised as absolute — "paused, so there is no row" — and a
    site_persona row is a row. Autofill still works on those pages; the choice
    just isn't kept, so it asks again rather than recording where you were."""

    def _tab(self, monkeypatch, url, private=False):
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: True)
        monkeypatch.setattr(browser, "active_tab",
                            lambda app: (url, "a title", private))

    def test_an_ordinary_page_is_keyed_on_its_host(self, two_identities, monkeypatch):
        self._tab(monkeypatch, "https://shop.example.com/checkout")
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["site"] == "shop.example.com"

    def test_a_private_window_is_never_keyed_on_its_url(self, two_identities, monkeypatch):
        self._tab(monkeypatch, "https://shop.example.com/checkout", private=True)
        who = server._persona_for_form(two_identities, "Safari", {})
        assert "shop.example.com" not in who["site"]
        assert who["url"] is None

    def test_a_site_on_the_dont_bother_list_is_not_recorded(
            self, two_identities, monkeypatch):
        from rewisp import config as cfg
        monkeypatch.setattr(cfg, "excluded_sites", lambda: ["shop.example.com"])
        self._tab(monkeypatch, "https://shop.example.com/checkout")
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["url"] is None

    def test_a_kill_listed_url_is_not_recorded(self, two_identities, monkeypatch):
        from rewisp import killlist
        monkeypatch.setattr(killlist.KillList, "reload",
                            lambda self: setattr(self, "url_patterns", ["bank.example"])
                            or setattr(self, "apps", set()))
        self._tab(monkeypatch, "https://bank.example.com/transfer")
        who = server._persona_for_form(two_identities, "Safari", {})
        assert who["url"] is None

    def test_autofill_still_works_there_it_just_is_not_remembered(
            self, two_identities, monkeypatch):
        self._tab(monkeypatch, "https://shop.example.com/x", private=True)
        who = server._persona_for_form(two_identities, "Safari", {"persona": "school"})
        assert who["persona"] == "school"        # the fill goes ahead
        assert who["url"] is None                # nothing is written down


class TestEmptyFoldersDoNotAskQuestions:
    """Settings lists a persona folder the moment it exists, so "Create the
    folders for me" isn't a dead end. Autofill must not follow suit: an empty
    persona answers identically to every other, so offering it turns "which you
    is this?" into four chips that all do the same thing, on every site."""

    def test_an_empty_folder_is_not_offered_at_a_form(self, conn, vault_dir):
        vault_dir("personal/info.md", "Email: me@gmail.com\n")
        personas.ensure_folders(conn, ["school", "work", "rewisp"])
        assert set(personas.known_personas(conn)) == {
            "personal", "school", "work", "rewisp"}          # Settings
        who = server._persona_for_form(conn, "Safari", {})
        assert [c["name"] for c in who["choices"]] == ["personal"]   # the form

    def test_a_half_set_up_vault_never_blocks_a_fill(self, conn, vault_dir):
        vault_dir("personal/info.md", "Email: me@gmail.com\n")
        personas.ensure_folders(conn, ["school", "work"])
        who = server._persona_for_form(conn, "Safari", {})
        # One choice -> the /form-write refusal (persona is None AND >1 choice)
        # cannot trigger, so the fill goes ahead as it always did.
        assert who["persona"] is None and len(who["choices"]) == 1

    def test_a_private_window_pick_does_not_settle_the_whole_browser(
            self, two_identities, monkeypatch):
        # Blanking the URL alone was not enough: with no URL the key falls back
        # to the APP, so one pick in a private window settled Safari itself and
        # the next private window filled without asking.
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: True)
        monkeypatch.setattr(browser, "active_tab",
                            lambda app: ("https://x.example.com/y", "t", True))
        who = server._persona_for_form(two_identities, "Safari", {"persona": "school"})
        assert who["remember"] is False
        assert who["site"] == ""
        # Nothing was written, so the next visit is unsettled and asks again.
        assert personas.for_site(two_identities, None, "Safari") is None


class TestABrowserWithNoURLNeverSettlesEverything:
    """site_key falls back to the app when there is no URL. For a browser that
    means `app::google chrome` — one pick settling every website in it. Firefox
    exposes no URL at all, and Automation consent can be denied or revoked for
    the rest, so this is a state real users are in."""

    def test_no_url_in_a_browser_is_not_remembered(self, two_identities, monkeypatch):
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: True)
        monkeypatch.setattr(browser, "active_tab", lambda app: (None, None, False))
        who = server._persona_for_form(two_identities, "Firefox", {"persona": "school"})
        assert who["remember"] is False
        assert who["site"] == ""
        assert who["persona"] == "school"      # the fill itself still happens

    def test_a_native_app_still_settles_on_the_app(self, two_identities, monkeypatch):
        # Mail has no URL and never will; the app IS the right unit there.
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: False)
        who = server._persona_for_form(two_identities, "Mail", {"persona": "work"})
        assert who["remember"] is True
        assert who["site"] == "app::mail"

    def test_consent_revoked_mid_session_does_not_settle_the_browser(
            self, two_identities, monkeypatch):
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: True)
        monkeypatch.setattr(browser, "active_tab",
                            lambda app: (_ for _ in ()).throw(OSError("no consent")))
        who = server._persona_for_form(two_identities, "Safari", {"persona": "school"})
        assert who["remember"] is False and who["site"] == ""


class TestEveryBrowser:
    """AppleScript is not available in every browser. Firefox exposes no
    scripting dictionary at all, and Automation consent can be denied or revoked
    for the rest — in both cases a persona choice could never be remembered, so
    those users were asked on every single form, forever. Accessibility carries
    the address on the web area for all of them."""

    def _no_applescript(self, monkeypatch):
        from rewisp import browser
        monkeypatch.setattr(browser, "is_browser", lambda app: True)
        monkeypatch.setattr(browser, "active_tab", lambda app: (None, None, False))

    def test_firefox_is_remembered_via_accessibility(self, two_identities, monkeypatch):
        from rewisp import form
        self._no_applescript(monkeypatch)
        monkeypatch.setattr(form, "page_url",
                            lambda pid: {"url": "https://shop.example.com/cart",
                                         "title": "Cart — Shop"})
        who = server._persona_for_form(two_identities, "Firefox", {}, pid=42)
        assert who["site"] == "shop.example.com"
        assert who["remember"] is True

    def test_a_private_window_is_still_caught_without_applescript(
            self, two_identities, monkeypatch):
        # AX says nothing about incognito, so the window title heuristic — the
        # same one the kill list already uses for Safari — has to hold the line.
        from rewisp import form
        self._no_applescript(monkeypatch)
        monkeypatch.setattr(form, "page_url",
                            lambda pid: {"url": "https://shop.example.com/cart",
                                         "title": "Cart — Private Browsing"})
        who = server._persona_for_form(two_identities, "Safari", {}, pid=42)
        assert who["remember"] is False and who["site"] == ""

    def test_the_kill_list_still_applies_to_an_ax_url(self, two_identities, monkeypatch):
        from rewisp import config as cfg, form
        self._no_applescript(monkeypatch)
        monkeypatch.setattr(cfg, "excluded_sites", lambda: ["shop.example.com"])
        monkeypatch.setattr(form, "page_url",
                            lambda pid: {"url": "https://shop.example.com/cart", "title": "Cart"})
        who = server._persona_for_form(two_identities, "Firefox", {}, pid=42)
        assert who["remember"] is False

    def test_no_pid_means_no_accessibility_attempt(self, two_identities, monkeypatch):
        from rewisp import form
        self._no_applescript(monkeypatch)
        called = []
        monkeypatch.setattr(form, "page_url", lambda pid: called.append(pid) or None)
        who = server._persona_for_form(two_identities, "Firefox", {})
        assert called == [] and who["remember"] is False

    def test_a_non_http_ax_value_is_ignored(self, two_identities, monkeypatch):
        # AXDocument can be a file:// path on a local page; that is not a site.
        from rewisp import form
        self._no_applescript(monkeypatch)
        monkeypatch.setattr(form, "page_url", lambda pid: None)
        who = server._persona_for_form(two_identities, "Firefox", {}, pid=42)
        assert who["remember"] is False
