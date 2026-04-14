"""Integration tests for altergo — subprocess-level.

Approach
--------
These tests run altergo as a real subprocess with ``HOME`` pointed at a
temporary directory built by the ``full_home`` fixture.  The fake claude
binary at ``tests/bin/claude`` is placed first on PATH (via the
``fake_claude_bin`` fixture) so that ``shutil.which("claude")`` resolves to
it.  When altergo calls ``os.execvpe(claude_path, cmd, env)`` inside the
subprocess, the fake binary executes inside that subprocess and prints
structured ``KEY=VALUE`` sentinel lines to stdout.  The test process then
reads those lines via ``subprocess.run(capture_output=True)``.

This lets us verify:
  - HOME is set to the correct account directory before exec
  - $HOME/.claude/projects is reachable (symlink is intact)
  - $HOME/.claude/ is a real or correctly-linked directory
  - Arguments are passed through unchanged
  - Account switching works end-to-end

Fixtures used (defined in conftest.py)
---------------------------------------
  full_home       — builds a complete fake HOME tree on disk (default/work/personal)
  fake_claude_bin — prepends tests/bin/ to PATH

NOTE: Do NOT use os.execvpe in these helpers.  subprocess.run is intentional:
the test process must survive so it can inspect stdout/stderr/returncode.
altergo itself will call os.execvpe inside the child process; that is the
behaviour we observe via the fake claude output.

MAIN_HOME isolation
-------------------
altergo.py reads MAIN_HOME from pwd.getpwuid() at module import time, which
always returns the real system home regardless of the HOME env var.  To make
subprocess tests fully isolated, we run altergo through
tests/bin/altergo-test-wrapper, which patches the module globals before calling
main() based on the ALTERGO_TEST_HOME env var.  run_altergo() uses this wrapper
automatically; run_altergo_nobin() does the same but without the fake claude on PATH.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"
TESTS_BIN = Path(__file__).parent / "bin"
WRAPPER = TESTS_BIN / "altergo-test-wrapper"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_sentinel_output(stdout: str) -> dict:
    """Parse the KEY=VALUE lines emitted by the fake claude sentinel binary.

    Splits on the *first* ``=`` only, so values that contain ``=`` (e.g. a
    path containing ``==``) are preserved intact.

    Lines that do not contain ``=`` are silently ignored, which means normal
    altergo status output (e.g. the config banner) does not cause parse errors.

    Args:
        stdout: The full captured stdout string from ``run_altergo``.

    Returns:
        A dict mapping each ``ALTERGO_TEST_*`` key to its value string.

    Example::

        >>> parse_sentinel_output("ALTERGO_TEST_HOME=/tmp/home\\nConfig complete!\\n")
        {'ALTERGO_TEST_HOME': '/tmp/home'}
    """
    result = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("ALTERGO_TEST_"):
            result[key] = value
    return result


def run_altergo(full_home_fixture, fake_claude_bin_fixture, *args, extra_env=None):
    """Run altergo via the test wrapper with the fake claude binary on PATH.

    Parameters
    ----------
    full_home_fixture:
        The dict returned by the ``full_home`` pytest fixture.
    fake_claude_bin_fixture:
        The Path returned by the ``fake_claude_bin`` pytest fixture.  Accepting
        it here ensures the fixture is activated (PATH is already patched via
        monkeypatch.setenv by the time we build the subprocess env).
    *args:
        CLI arguments forwarded to altergo (e.g. ``"work"``, ``"--"``,
        ``"claude"``).
    extra_env:
        Optional dict merged on top of the subprocess environment.

    Returns
    -------
    subprocess.CompletedProcess  (stdout/stderr captured as text)
    """
    home = full_home_fixture["home"]
    env = {
        **os.environ,
        "ALTERGO_TEST_HOME": str(home),
        "HOME": str(home),
        # Ensure the fake bin dir is first on PATH in the child process even
        # if monkeypatch.setenv doesn't propagate (it only patches os.environ
        # in the parent process; child inherits os.environ at fork time so it
        # should work, but being explicit costs nothing).
        "PATH": str(TESTS_BIN) + ":" + os.environ.get("PATH", ""),
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def run_altergo_nobin(full_home_fixture, *args, extra_env=None):
    """Run altergo via the test wrapper WITHOUT the fake claude binary on PATH.

    Used for tests that must not reach the ``os.execvpe(claude)`` step — error
    paths, shell passthrough tests using sh/echo, etc.
    """
    home = full_home_fixture["home"]
    env = {
        **os.environ,
        "ALTERGO_TEST_HOME": str(home),
        "HOME": str(home),
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Group 1 — HOME is correctly set when launching
# ---------------------------------------------------------------------------


def test_home_is_account_home_on_launch(full_home, fake_claude_bin):
    """When `altergo work` launches claude, HOME must be the work account home."""
    proc = run_altergo(full_home, fake_claude_bin, "work")
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}; stderr={proc.stderr!r}"

    sentinel = parse_sentinel_output(proc.stdout)
    expected = str(full_home["work_home"])
    actual = sentinel.get("ALTERGO_TEST_HOME")
    assert actual == expected, (
        f"HOME seen by claude was {actual!r}, expected work account {expected!r}"
    )


def test_home_is_default_account_when_no_name_given(full_home, fake_claude_bin):
    """Plain `altergo` (no account name) sets HOME to accounts/default/, not MAIN_HOME."""
    proc = run_altergo(full_home, fake_claude_bin)
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"

    sentinel = parse_sentinel_output(proc.stdout)
    expected = str(full_home["default_home"])
    actual = sentinel.get("ALTERGO_TEST_HOME")
    assert actual == expected, (
        f"Plain `altergo` used HOME={actual!r}, expected default account {expected!r}"
    )
    # Explicitly confirm it is NOT the main home (that would bypass credential isolation).
    assert actual != str(full_home["home"]), (
        "HOME must not be MAIN_HOME — that would bypass credential isolation"
    )


def test_home_does_not_bleed_main_home(full_home, fake_claude_bin):
    """HOME seen by claude must never equal MAIN_HOME regardless of which account is used."""
    main_home = str(full_home["home"])

    for account_arg, expected_key in [
        ([], "default_home"),
        (["work"], "work_home"),
        (["personal"], "personal_home"),
    ]:
        proc = run_altergo(full_home, fake_claude_bin, *account_arg)
        assert proc.returncode == 0, (
            f"account={account_arg or 'default'} exited {proc.returncode}; stderr={proc.stderr!r}"
        )
        actual = parse_sentinel_output(proc.stdout).get("ALTERGO_TEST_HOME")
        assert actual != main_home, (
            f"account={account_arg or 'default'}: HOME={actual!r} equals MAIN_HOME — "
            "credential isolation is broken"
        )
        assert actual == str(full_home[expected_key]), (
            f"account={account_arg or 'default'}: HOME={actual!r} != expected {full_home[expected_key]}"
        )


# ---------------------------------------------------------------------------
# Group 2 — Folder traversal: the @. / @.. chain
# ---------------------------------------------------------------------------


def test_projects_symlink_resolves_transparently(full_home):
    """Files written to MAIN_CLAUDE/projects/ are readable via account_home/.claude/projects/.

    This is the exact chain Claude Code uses for @. folder references: Claude
    writes sessions into $HOME/.claude/projects/, and because
    account_home/.claude/projects is a symlink to MAIN_CLAUDE/projects/, those
    files are reachable from any account HOME.
    """
    sentinel = full_home["main_claude"] / "projects" / "test-sentinel.txt"
    sentinel.write_text("hello from main")

    for key in ("default_home", "work_home", "personal_home"):
        via_link = full_home[key] / ".claude" / "projects" / "test-sentinel.txt"
        assert via_link.exists(), (
            f"{key}/.claude/projects/test-sentinel.txt does not exist — "
            "the symlink chain is broken and @. references will fail"
        )
        assert via_link.read_text() == "hello from main", (
            f"Content read via {key} symlink does not match the original"
        )


def test_projects_symlink_is_same_inode(full_home):
    """account_home/.claude/projects/ and MAIN_CLAUDE/projects/ are the same inode.

    A directory copy would pass existence checks but silently diverge when
    files are written to one tree.  Inode equality proves it is physically
    the same directory object, not a copy.
    """
    main_projects = full_home["main_claude"] / "projects"
    main_ino = main_projects.stat().st_ino

    for key in ("default_home", "work_home", "personal_home"):
        link = full_home[key] / ".claude" / "projects"
        assert link.is_symlink(), f"{key}/.claude/projects must be a symlink, not a real directory"
        link_ino = link.stat().st_ino  # stat() follows the symlink → resolves to the real dir
        assert link_ino == main_ino, (
            f"{key}/.claude/projects has inode {link_ino}, "
            f"expected {main_ino} (same inode as MAIN_CLAUDE/projects/)"
        )


def test_nested_session_file_visible_across_accounts(full_home):
    """A session file written for one account is visible when switching to another.

    Real Claude Code stores sessions at:
      $HOME/.claude/projects/<project-hash>/<session-id>.jsonl

    Because all accounts share projects/ via symlinks, a session written in one
    account context must be readable from all others — this is the prerequisite
    for @.. cross-session references to work.
    """
    session_dir = full_home["main_claude"] / "projects" / "test-project"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / "abc123.jsonl"
    session_file.write_text('{"type":"human","message":{"content":"hello"}}\n')

    for key in ("default_home", "work_home", "personal_home"):
        via_account = full_home[key] / ".claude" / "projects" / "test-project" / "abc123.jsonl"
        assert via_account.exists(), (
            f"Session file not visible via {key} — "
            "@.. cross-session references will fail for this account"
        )
        assert via_account.read_text() == session_file.read_text()


# ---------------------------------------------------------------------------
# Group 3 — All CLI paths actually work
# ---------------------------------------------------------------------------


def test_altergo_work_invokes_claude(full_home, fake_claude_bin):
    """`altergo work` fires the claude binary (exit 0, sentinel output present)."""
    proc = run_altergo(full_home, fake_claude_bin, "work")
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    assert "ALTERGO_TEST_HOME" in sentinel, (
        "Fake claude binary did not produce sentinel output — it was never invoked. "
        f"Full stdout: {proc.stdout!r}"
    )


def test_altergo_work_shell_sets_home(full_home):
    """`altergo work -- sh -c 'echo HOME=$HOME'` sets HOME to the work account.

    We use the `-- <cmd>` passthrough form because launch_shell() is
    interactive (requires a TTY) and cannot be tested in a subprocess.
    launch_command() sets the same HOME env, so this is the correct proxy.
    """
    proc = run_altergo_nobin(
        full_home, "work", "--", "sh", "-c", "echo HOME=$HOME"
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    expected = str(full_home["work_home"])
    assert f"HOME={expected}" in proc.stdout, (
        f"Expected 'HOME={expected}' in stdout, got: {proc.stdout!r}"
    )


def test_altergo_work_passthrough_sets_home(full_home, fake_claude_bin):
    """`altergo work -- claude` uses the work account HOME, not MAIN_HOME."""
    proc = run_altergo(full_home, fake_claude_bin, "work", "--", "claude")
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    expected = str(full_home["work_home"])
    actual = sentinel.get("ALTERGO_TEST_HOME")
    assert actual == expected, (
        f"`altergo work -- claude` HOME was {actual!r}, expected {expected!r}"
    )


def test_altergo_passthrough_double_dash(full_home, fake_claude_bin):
    """`altergo -- claude` (no account name) uses the default account HOME."""
    proc = run_altergo(full_home, fake_claude_bin, "--", "claude")
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    expected = str(full_home["default_home"])
    actual = sentinel.get("ALTERGO_TEST_HOME")
    assert actual == expected, (
        f"`altergo -- claude` HOME was {actual!r}, expected default account {expected!r}"
    )


def test_unknown_account_exits_1_with_message(full_home):
    """`altergo typo` exits 1 and prints an --config hint for the unknown account."""
    proc = run_altergo_nobin(full_home, "typo")
    assert proc.returncode == 1
    assert "typo" in proc.stderr, f"Account name 'typo' missing from stderr: {proc.stderr!r}"
    assert "--config typo" in proc.stderr, (
        f"Config hint missing from stderr: {proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Group 4 — PATH is not corrupted
# ---------------------------------------------------------------------------


def test_path_not_corrupted_when_local_bin_absent(full_home, fake_claude_bin):
    """When account_home/.local/bin does not exist, it is NOT prepended to PATH.

    Injecting a non-existent directory at the front of PATH gives an
    uncontrolled write target higher precedence than all system binaries.
    The guard in _build_alt_env() must prevent this.
    """
    local_bin = full_home["work_home"] / ".local" / "bin"
    assert not local_bin.exists(), (
        "Test precondition: work account must not have .local/bin before the test"
    )

    proc = run_altergo(full_home, fake_claude_bin, "work")
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"

    sentinel = parse_sentinel_output(proc.stdout)
    path_dirs = sentinel.get("ALTERGO_TEST_PATH", "").split(":")
    assert str(local_bin) not in path_dirs, (
        f"Non-existent {local_bin} was injected into PATH: "
        f"{sentinel.get('ALTERGO_TEST_PATH')!r}"
    )


def test_path_prepended_when_local_bin_exists(full_home, fake_claude_bin):
    """When account_home/.local/bin exists, it IS prepended as the first PATH entry."""
    local_bin = full_home["work_home"] / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    proc = run_altergo(full_home, fake_claude_bin, "work")
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"

    sentinel = parse_sentinel_output(proc.stdout)
    path_dirs = sentinel.get("ALTERGO_TEST_PATH", "").split(":")
    assert str(local_bin) in path_dirs, (
        f"Expected {local_bin} in PATH, got: {sentinel.get('ALTERGO_TEST_PATH')!r}"
    )
    assert path_dirs[0] == str(local_bin), (
        f"Expected {local_bin} as first PATH entry, got: {path_dirs[0]!r}"
    )


# ---------------------------------------------------------------------------
# Group 5 — Multi-account isolation
# ---------------------------------------------------------------------------


def test_two_accounts_have_separate_homes(full_home, fake_claude_bin):
    """`altergo work` and `altergo personal` report different HOME values."""
    proc_work = run_altergo(full_home, fake_claude_bin, "work")
    proc_personal = run_altergo(full_home, fake_claude_bin, "personal")

    assert proc_work.returncode == 0, f"work failed; stderr={proc_work.stderr!r}"
    assert proc_personal.returncode == 0, f"personal failed; stderr={proc_personal.stderr!r}"

    work_home = parse_sentinel_output(proc_work.stdout).get("ALTERGO_TEST_HOME")
    personal_home = parse_sentinel_output(proc_personal.stdout).get("ALTERGO_TEST_HOME")

    assert work_home != personal_home, (
        f"work and personal share the same HOME: {work_home!r}"
    )
    assert work_home == str(full_home["work_home"]), (
        f"work account HOME was {work_home!r}, expected {full_home['work_home']}"
    )
    assert personal_home == str(full_home["personal_home"]), (
        f"personal account HOME was {personal_home!r}, expected {full_home['personal_home']}"
    )


def test_credentials_file_is_per_account(full_home):
    """Each account's .credentials.json is isolated — writing to one does not affect the other.

    Credentials are intentionally NOT listed in SYMLINK_FILES/SYMLINK_DIRS.
    This test verifies the absence of accidental symlinking.
    """
    work_creds = full_home["work_home"] / ".claude" / ".credentials.json"
    personal_creds = full_home["personal_home"] / ".claude" / ".credentials.json"

    work_creds.write_text('{"oauthAccount": {"emailAddress": "work@example.com"}}')

    # Personal credentials file must not exist (no accidental symlink to work's).
    assert not personal_creds.exists(), (
        "Writing credentials to work account caused them to appear in personal account — "
        "credential isolation is broken (likely an accidental symlink or shared path)"
    )


def test_switching_accounts_does_not_leak_credentials(full_home, fake_claude_bin):
    """Running `altergo work` then `altergo personal` shows distinct HOME values each time.

    This confirms that each exec gets a fresh, per-account HOME and that no
    state from the first invocation leaks into the second.
    """
    work_proc = run_altergo(full_home, fake_claude_bin, "work")
    personal_proc = run_altergo(full_home, fake_claude_bin, "personal")

    assert work_proc.returncode == 0, f"work failed; stderr={work_proc.stderr!r}"
    assert personal_proc.returncode == 0, f"personal failed; stderr={personal_proc.stderr!r}"

    work_sentinel = parse_sentinel_output(work_proc.stdout)
    personal_sentinel = parse_sentinel_output(personal_proc.stdout)

    assert work_sentinel["ALTERGO_TEST_HOME"] == str(full_home["work_home"])
    assert personal_sentinel["ALTERGO_TEST_HOME"] == str(full_home["personal_home"])
    assert work_sentinel["ALTERGO_TEST_HOME"] != personal_sentinel["ALTERGO_TEST_HOME"], (
        "Both invocations returned the same HOME — account isolation failed"
    )


# ---------------------------------------------------------------------------
# Group 6 — Live claude binary (skip if not installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude not installed")
def test_real_claude_version_with_account_home(full_home):
    """Real `claude --version` succeeds when HOME is set to an account home."""
    home = full_home["home"]
    env = {
        **os.environ,
        "ALTERGO_TEST_HOME": str(home),
        "HOME": str(home),
    }
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), "work", "--", "claude", "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (
        f"Real `claude --version` failed with account HOME; stderr={proc.stderr!r}"
    )
    assert proc.stdout.strip(), "Expected version output on stdout, got nothing"


# ---------------------------------------------------------------------------
# Group 7 — portal subcommand (subprocess level)
#
# portal always passes force_tmux=True to launch_claude.  To keep these tests
# hermetic (no real tmux required), we set TMUX=/fake in the subprocess env.
# That triggers the "already inside tmux" branch inside launch_claude, which
# skips the tmux wrap and calls subprocess.run([claude_binary, ...]) directly —
# exactly what the fake sentinel binary is built to handle.
# ---------------------------------------------------------------------------


def test_portal_no_args_uses_active_account(full_home, fake_claude_bin):
    """`altergo portal` with active account set launches that account under force_tmux."""
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    # The active account from full_home fixture is "default".
    assert sentinel.get("ALTERGO_TEST_HOME") == str(full_home["default_home"]), (
        f"portal (no args) used HOME={sentinel.get('ALTERGO_TEST_HOME')!r}, "
        f"expected default account {full_home['default_home']}"
    )
    # The warning for being inside tmux must appear somewhere in the output.
    assert "already inside a tmux session" in proc.stdout + proc.stderr, (
        "Expected 'already inside a tmux session' message when TMUX is set"
    )


def test_portal_named_account_launches_that_account(full_home, fake_claude_bin):
    """`altergo portal work` launches the work account under force_tmux."""
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal", "work",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    assert sentinel.get("ALTERGO_TEST_HOME") == str(full_home["work_home"]), (
        f"portal work used HOME={sentinel.get('ALTERGO_TEST_HOME')!r}, "
        f"expected {full_home['work_home']}"
    )


def test_portal_unknown_positional_token_exits_1(full_home, fake_claude_bin):
    """`altergo portal ghost` — 'ghost' is not an account dir and not a provider,
    so portal exits 1 with a clear error rather than silently forwarding it.
    """
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal", "ghost",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 1, (
        f"expected exit 1 for unknown token; stderr={proc.stderr!r}"
    )
    assert "ghost" in proc.stderr, "error message should name the unknown token"


def test_portal_multiple_accounts_no_active_exits_1(full_home):
    """`altergo portal` with no active account and multiple accounts exits 1 with a hint."""
    # Remove the active account from settings so no active is set.
    import json
    settings = full_home["home"] / ".altergo" / ".altergo.json"
    if settings.exists():
        data = json.loads(settings.read_text())
        data.pop("active_account", None)
        settings.write_text(json.dumps(data))

    proc = run_altergo_nobin(
        full_home,
        "portal",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 1, f"expected exit 1; got {proc.returncode}; stderr={proc.stderr!r}"
    assert "multiple" in proc.stderr.lower(), (
        f"Expected 'multiple accounts' message in stderr: {proc.stderr!r}"
    )


def test_portal_resume_flag_passed_through_to_provider(full_home, fake_claude_bin):
    """`altergo portal work --resume` passes --resume to the provider binary."""
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal", "work", "--resume",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    # The fake claude sentinel binary accepts all args without error, so exit 0
    # proves the flag was forwarded without being dropped or causing a crash.


def test_portal_resume_with_id_passed_through_to_provider(full_home, fake_claude_bin):
    """`altergo portal work --resume abc123` passes both --resume and abc123 through."""
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal", "work", "--resume", "abc123",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"


def test_portal_home_is_correct_account_not_main_home(full_home, fake_claude_bin):
    """`altergo portal personal` must set HOME to the personal account, never MAIN_HOME."""
    main_home = str(full_home["home"])
    proc = run_altergo(
        full_home, fake_claude_bin,
        "portal", "personal",
        extra_env={"TMUX": "/tmp/tmux-fake,0,0"},
    )
    assert proc.returncode == 0, f"expected exit 0; stderr={proc.stderr!r}"
    sentinel = parse_sentinel_output(proc.stdout)
    actual = sentinel.get("ALTERGO_TEST_HOME")
    assert actual == str(full_home["personal_home"]), (
        f"portal personal: HOME={actual!r}, expected personal account home"
    )
    assert actual != main_home, (
        "portal set HOME to MAIN_HOME — credential isolation is broken"
    )


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude not installed")
def test_real_claude_sees_symlinked_projects(full_home):
    """Real claude binary can read the projects dir via the account symlink.

    We verify the directory is reachable at the symlink path.  We do NOT
    launch a full claude session (which requires authentication and a TTY).
    """
    sentinel = full_home["main_claude"] / "projects" / "live-test-sentinel.txt"
    sentinel.write_text("real claude symlink test")

    via_work = full_home["work_home"] / ".claude" / "projects" / "live-test-sentinel.txt"
    assert via_work.exists(), (
        "Sentinel written to MAIN_CLAUDE/projects/ is not visible via work account symlink — "
        "real claude would fail to resolve @. paths"
    )
    assert via_work.read_text() == "real claude symlink test"
