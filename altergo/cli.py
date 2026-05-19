import sys

import altergo.constants as _const
from altergo._version import __version__
from altergo.accounts import (
    _account_for_provider,
    _native_supports_provider,
    configure_account,
    do_add_provider,
    do_default_provider,
    do_remove_provider,
    do_rename,
    do_star,
    do_teardown,
    get_active_account,
    list_accounts,
    resolve_account,
    set_active_account,
    validate_account_name,
)
from altergo.keychain import _run_oauth_token_setup
from altergo.persistence import (
    load_account_meta,
    load_persisted_theme,
    maybe_rotate_random_theme,
    save_native_default_provider,
    save_persisted_theme,
)
from altergo.runner import (
    _extract_yolo_resume,
    _looks_like_account,
    launch_claude,
    launch_command,
    launch_shell,
)
from altergo.sessions import decode_project_path, get_sessions
from altergo.theme import THEMES, C, _c, get_current_theme, set_current_theme
from altergo.tui.config_tui import (
    _prompt_config_menu,
    _prompt_new_account_name_tui,
    _prompt_provider_picker,
)
from altergo.tui.launcher import (
    _first_run_onboarding,
    _prompt_yolo_account_picker,
    interactive_launcher,
)
from altergo.tui.picker import interactive_picker
from altergo.tui.search import interactive_search
from altergo.tui.settings_tui import interactive_settings
from altergo.ui import _status_wrap, show_banner, show_help


def main():
    # Load the user's persisted theme before anything prints so the banner,
    # help output, and curses screens all share one palette from the first
    # character onward.
    set_current_theme(load_persisted_theme())
    maybe_rotate_random_theme()
    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        show_help()
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--config":
        # Supported forms:
        #   altergo --config                                    (interactive)
        #   altergo --config <name>                             (named, interactive provider picker)
        #   altergo --config <name> --provider claude           (fully specified)
        #   altergo --config --provider gemini                  (interactive name, specified provider)
        #   altergo --config <name> --keychain keychain|none  (non-interactive keychain mode)
        remaining = args[1:]
        name = None
        provider_arg = None
        keychain_arg = None  # "keychain", "none", or None (prompt/default)
        i = 0
        while i < len(remaining):
            if remaining[i] == "--provider" and i + 1 < len(remaining):
                provider_arg = remaining[i + 1]
                i += 2
            elif remaining[i] == "--keychain" and i + 1 < len(remaining):
                keychain_arg = remaining[i + 1]
                if keychain_arg in ("system", "shared", "isolated", "dedicated"):
                    # v0.46.0: all legacy aliases removed — hard error.
                    print(
                        f"error: argument --keychain: invalid choice: '{keychain_arg}'"
                        " (choose from 'keychain', 'none')",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                elif keychain_arg not in ("keychain", "none"):
                    print(
                        f"error: argument --keychain: invalid choice: '{keychain_arg}'"
                        " (choose from 'keychain', 'none')",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                i += 2
            elif not remaining[i].startswith("--") and name is None:
                name = remaining[i]
                validate_account_name(name)
                i += 1
            else:
                i += 1

        # Resolve name
        if name is None:
            if sys.stdin.isatty():
                existing_accts = list_accounts()
                if existing_accts:
                    picked = _prompt_config_menu(existing_accts)
                else:
                    picked = _prompt_new_account_name_tui([])
                if picked is None:
                    sys.exit(0)
                name = picked
            else:
                name = "default"
            validate_account_name(name)

        # Resolve provider (exactly one)
        if provider_arg is not None:
            if provider_arg not in _const.PROVIDERS:
                print(
                    f"altergo: unknown provider '{provider_arg}'. Known: {', '.join(_const.PROVIDERS)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            cfg_provider = provider_arg
        else:
            if sys.stdin.isatty():
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                current = meta["default_provider"] if meta else None
                cfg_provider = _prompt_provider_picker(current)
            else:
                # Non-interactive: default to claude (backwards compat)
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                cfg_provider = meta["default_provider"] if meta else "claude"

        configure_account(name, cfg_provider, keychain_arg=keychain_arg)
        sys.exit(0)

    if args and args[0] == "--rename":
        if len(args) < 3:
            print("altergo: usage: altergo --rename <old-name> <new-name>", file=sys.stderr)
            sys.exit(1)
        do_rename(args[1], args[2])
        sys.exit(0)

    if args and args[0] == "--teardown":
        # Support: --teardown --name <name>
        name = "default"
        if len(args) >= 3 and args[1] == "--name":
            name = args[2]
            if name in _const._RESERVED_NAMES:
                print(f"altergo: '{name}' is a reserved name and cannot be torn down.", file=sys.stderr)
                sys.exit(1)
        do_teardown(name)
        sys.exit(0)

    if args and args[0] == "--settings":
        interactive_settings()
        sys.exit(0)

    if args and args[0] == "--setup-token":
        # altergo --setup-token <account>
        # Re-run just the OAuth token setup for an existing account. Useful
        # when the user skipped the offer during --config, or needs to
        # rotate after revocation. Account must already exist; we do not
        # create it here.
        if len(args) < 2:
            print(
                "altergo: usage: altergo --setup-token <account>",
                file=sys.stderr,
            )
            sys.exit(1)
        target = args[1]
        if target == _const._NATIVE_ACCOUNT:
            account_home = None
        else:
            acct_dir = _const.ACCOUNTS_DIR / target
            if not acct_dir.is_dir():
                print(
                    f"altergo: account '{target}' not found. Run 'altergo --config {target}' first.",
                    file=sys.stderr,
                )
                sys.exit(1)
            account_home = acct_dir
        ok = _run_oauth_token_setup(target, account_home)
        sys.exit(0 if ok else 1)

    if args and args[0] == "--launch":
        interactive_launcher()
        sys.exit(0)

    if args and args[0] == "--theme":
        # `altergo --theme`         → print current + catalog
        # `altergo --theme <name>`  → set persistently
        if len(args) == 1:
            show_banner()
            cur = get_current_theme()
            print(f"  current: {_c(C('command'), THEMES[cur]['display_name'])}  ({cur})")
            print()
            print(_c(C("header"), "  Available themes"))
            for tid, t in THEMES.items():
                marker = _c(C("success"), "●") if tid == cur else " "
                name = _c(C("command"), t["display_name"].ljust(10))
                print(f"  {marker} {name}  {_c(C('dim'), t['description'])}")
            print()
            print(_c(C("dim"), "  Set with: altergo --theme <theme>   ·   or press 't' in the launcher"))
            sys.exit(0)
        name = args[1]
        if name not in THEMES:
            print(
                f"altergo: unknown theme '{name}'. Known: {', '.join(THEMES.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)
        set_current_theme(name)
        save_persisted_theme(name)
        show_banner()
        print(
            f"  theme set to {_c(C('command'), THEMES[name]['display_name'])}  "
            f"{_c(C('dim'), '— ' + THEMES[name]['description'])}"
        )
        sys.exit(0)

    # --recall → open the interactive session picker across all accounts.
    # Account is resolved from the selected session's provider (not chosen
    # up front), so multi-account setups don't need --use or a positional name.
    if args and args[0] == "--recall":
        if not list_accounts():
            print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
            sys.exit(1)
        show_banner()
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        selected = interactive_picker(sessions)
        if not selected:
            print("Cancelled.")
            sys.exit(0)
        provider_id = selected.get("provider", "claude")
        recall_account = _account_for_provider(provider_id)
        if recall_account is None:
            print(
                f"altergo: no account configured for provider '{provider_id}'.\n"
                f"  Create one with: altergo --config <account> --provider {provider_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        recall_cwd = selected.get("cwd") or decode_project_path(selected.get("project", ""))
        launch_claude(recall_account, ["--resume", selected["id"]], cwd=recall_cwd or None)
        sys.exit(0)

    # --yolo-resume [<id>] → resume a session with skip-permissions flags.
    # Intercept before account/provider resolution so the user never has to
    # specify an account name; we derive it from the session metadata.
    #
    # Subcommands like `portal` have their own arg parser that already routes
    # --yolo-resume correctly through launch_claude. If we see one in the args,
    # bail out of the global interceptor and let that handler take over —
    # otherwise leftover positionals (`portal`, `native`, `claude`) end up as
    # provider argv junk after --resume <id>.
    _yr_present, _yr_session_id, _yr_rest = _extract_yolo_resume(args)
    _yr_subcommand_present = any(tok in ("portal", "shell") for tok in _yr_rest)
    if _yr_present and not _yr_subcommand_present:
        # Honor a leading explicit account token (e.g. `altergo native --yolo-resume <id>`
        # or `altergo work --yolo-resume <id>`) so it isn't silently dropped.
        _yr_explicit_account: str | None = None
        if _yr_rest and _looks_like_account(_yr_rest[0]):
            _cand = _yr_rest[0]
            if _cand == _const._NATIVE_ACCOUNT or (_const.ACCOUNTS_DIR / _cand).is_dir():
                _yr_explicit_account = _cand
                _yr_rest = _yr_rest[1:]

        # An explicit provider token may follow the account (e.g.
        # `altergo native claude --yolo-resume <id>`). Consume it so it isn't
        # passed to launch_claude as positional argv junk.
        _yr_explicit_provider: str | None = None
        if _yr_rest and _yr_rest[0] in _const.PROVIDERS:
            _yr_explicit_provider = _yr_rest[0]
            _yr_rest = _yr_rest[1:]

        # Native passes through to the provider's own resume mechanism — sessions
        # live in the real $HOME and the provider already has a picker, so altergo
        # must not scan or show its own list here. Native works without any
        # managed accounts so we short-circuit before the accounts check below.
        if _yr_explicit_account == _const._NATIVE_ACCOUNT:
            _yr_passthrough = ["--yolo-resume"]
            if _yr_session_id is not None:
                _yr_passthrough.append(_yr_session_id)
            sys.exit(
                launch_claude(
                    _const._NATIVE_ACCOUNT,
                    _yr_passthrough + _yr_rest,
                    provider=_yr_explicit_provider,
                )
            )

        if not list_accounts():
            print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
            sys.exit(1)

        if _yr_session_id is None:
            # Case 1: no ID — open the interactive picker, then launch with yolo.
            show_banner()
            _yr_sessions = _status_wrap("Scanning sessions…", get_sessions)
            _yr_selected = interactive_picker(_yr_sessions)
            if not _yr_selected:
                print("Cancelled.")
                sys.exit(0)
            _yr_provider = _yr_selected.get("provider", "claude")
            _yr_skip = list(_const.PROVIDERS.get(_yr_provider, {}).get("flags", {}).get("skip_perms", []))
            if _yr_explicit_account is not None:
                _yr_account = _yr_explicit_account
            else:
                _yr_account = _account_for_provider(_yr_provider)
            if _yr_account is None:
                print(
                    f"altergo: no account configured for provider '{_yr_provider}'.\n"
                    f"  Create one with: altergo --config <account> --provider {_yr_provider}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _yr_cwd = _yr_selected.get("cwd") or decode_project_path(_yr_selected.get("project", ""))
            launch_claude(_yr_account, ["--resume", _yr_selected["id"]] + _yr_skip + _yr_rest, cwd=_yr_cwd or None)
            sys.exit(0)
        else:
            # Case 2: ID given — find session metadata, pick account, launch.
            _yr_all_sessions = _status_wrap("Scanning sessions…", get_sessions)
            _yr_match = next((s for s in _yr_all_sessions if s["id"] == _yr_session_id), None)
            if _yr_match is None:
                print(
                    _c(
                        C("warn"),
                        f"  altergo: session '{_yr_session_id}' not found in local history "
                        f"— continuing anyway (the provider will validate the ID).",
                    ),
                    file=sys.stderr,
                )
                _yr_provider = "claude"
                _yr_cwd = None
            else:
                _yr_provider = _yr_match.get("provider", "claude")
                _yr_cwd = _yr_match.get("cwd") or decode_project_path(_yr_match.get("project", ""))

            _yr_skip = list(_const.PROVIDERS.get(_yr_provider, {}).get("flags", {}).get("skip_perms", []))

            if _yr_explicit_account is not None:
                # User specified an explicit account — honor it, skip the picker.
                _yr_account = _yr_explicit_account
            else:
                # Determine which accounts support this provider.
                def _yr_has_provider(acct_name: str) -> bool:
                    _m = load_account_meta(_const.ACCOUNTS_DIR / acct_name)
                    if _m is None:
                        return _yr_provider == "claude"
                    return _yr_provider in _m["providers"]

                _yr_eligible = [a for a in list_accounts() if _yr_has_provider(a)]
                _yr_native_ok = _native_supports_provider(_yr_provider)

                if not _yr_eligible and not _yr_native_ok:
                    print(
                        f"altergo: no account configured for provider '{_yr_provider}'.\n"
                        f"  Create one with: altergo --config <account> --provider {_yr_provider}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

                _yr_active = get_active_account()
                _yr_active_eligible = (_yr_active in _yr_eligible) or (
                    _yr_active == _const._NATIVE_ACCOUNT and _yr_native_ok
                )
                if _yr_active_eligible:
                    _yr_account = _yr_active
                else:
                    _yr_picked = _prompt_yolo_account_picker(_yr_eligible, provider=_yr_provider)
                    if _yr_picked is None:
                        print("Cancelled.")
                        sys.exit(0)
                    _yr_account = _yr_picked

            launch_claude(_yr_account, ["--resume", _yr_session_id] + _yr_skip + _yr_rest, cwd=_yr_cwd or None)
            sys.exit(0)

    if args and args[0] == "--use":
        if len(args) < 2:
            print("altergo: --use requires an account name. Example: altergo --use work", file=sys.stderr)
            sys.exit(1)
        use_name = args[1]
        if use_name != _const._NATIVE_ACCOUNT and not (_const.ACCOUNTS_DIR / use_name).is_dir():
            print(
                f"altergo: account '{use_name}' not found. Run 'altergo --config {use_name}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        set_active_account(use_name)
        print(f"altergo: active account set to {_c(C('command'), use_name)}")
        print(_c(C("dim"), f"  Bare 'altergo' will now launch '{use_name}' by default."))
        sys.exit(0)

    # --star [<id>] → star the last or specified session
    if args and args[0] == "--star":
        session_id = args[1] if len(args) > 1 else None
        do_star(session_id)
        sys.exit(0)

    # --search → full-text conversation search
    if args and args[0] == "--search":
        show_banner()
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        selected = interactive_search(sessions)
        if selected:
            accounts = list_accounts()
            if len(accounts) == 1:
                search_account = accounts[0]
            else:
                active = get_active_account()
                search_account = active if active else accounts[0]
            search_cwd = selected.get("cwd") or decode_project_path(selected.get("project", ""))
            launch_claude(search_account, ["--resume", selected["id"]], cwd=search_cwd or None)
        else:
            print("Cancelled.")
        sys.exit(0)

    # altergo portal [<account>] [<provider>] [flags...]
    if args and args[0] == "portal":
        portal_args = args[1:]
        p_account = None
        p_provider = None
        p_remaining = []
        seen_flag = False
        for tok in portal_args:
            if tok.startswith("-"):
                seen_flag = True
                p_remaining.append(tok)
            elif seen_flag:
                # Value following a flag (e.g. session ID after --resume) — pass through
                p_remaining.append(tok)
            elif p_account is None and tok == _const._NATIVE_ACCOUNT:
                p_account = tok
            elif p_account is None and (_const.ACCOUNTS_DIR / tok).is_dir():
                p_account = tok
            elif p_provider is None and tok in _const.PROVIDERS:
                p_provider = tok
            else:
                # Unknown positional token before any flags — not an account or provider
                print(
                    f"altergo: portal: unknown account or provider '{tok}'.\n"
                    f"  Run 'altergo' to see accounts, or 'altergo --help' for usage.",
                    file=sys.stderr,
                )
                sys.exit(1)

        if p_account is None:
            _all = list_accounts()
            _active = get_active_account()
            if _active:
                p_account = _active
            elif len(_all) == 1:
                p_account = _all[0]
            elif not _all:
                print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
                sys.exit(1)
            else:
                print(
                    f"altergo: multiple accounts ({', '.join(_all)}) — specify one: altergo portal <account>",
                    file=sys.stderr,
                )
                sys.exit(1)

        launch_claude(p_account, p_remaining, provider=p_provider, force_tmux=True)
        sys.exit(0)

    # Account name as first positional arg
    # altergo <name> [sub-command | claude flags...]
    account = None
    if args and _looks_like_account(args[0]):
        candidate = args[0]
        if candidate == _const._NATIVE_ACCOUNT:
            # Native account: no managed directory — runs with the real $HOME.
            account = candidate
            args = args[1:]
        else:
            acct_home = _const.ACCOUNTS_DIR / candidate
            if not acct_home.is_dir():
                print(
                    f"altergo: account '{candidate}' not found. Run 'altergo --config {candidate}' to create it.",
                    file=sys.stderr,
                )
                sys.exit(1)
            account = candidate
            args = args[1:]

    # Implicit account resolution (no positional name given)
    if account is None:
        _all_accounts = list_accounts()
        _active = get_active_account()
        if _active:
            account = _active
            # The banner printed by launch_claude/launch_shell already shows
            # the account name beneath the logo, so no extra prefix line.
        elif len(_all_accounts) == 1:
            account = _all_accounts[0]
        elif len(_all_accounts) > 1 and sys.stdout.isatty():
            # Pass-through case: the user ran `altergo <flags>` with no active
            # account. We route the original args through the picker so e.g.
            # --yolo-resume <id> isn't silently dropped when the user picks.
            if args:
                _preview = " ".join(args)
                if len(_preview) > 60:
                    _preview = _preview[:57] + "..."
                _ctx = f"No default account set. Pick one — '{_preview}' will run against it."
                interactive_launcher(pending_args=args, context_msg=_ctx)
            else:
                interactive_launcher()
            sys.exit(0)
        elif not _all_accounts:
            if sys.stdout.isatty():
                _first_run_onboarding()
                sys.exit(0)
            else:
                print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
                sys.exit(1)
        else:
            # Multiple accounts, non-interactive — cannot pick one silently
            print(
                f"altergo: multiple accounts exist ({', '.join(_all_accounts)}).\n"
                f"  Run 'altergo <account>' to launch a specific account, or\n"
                f"  'altergo --use <account>' to set an active account for bare 'altergo'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Sub-commands (after optional account prefix) ──────────────────────────

    # altergo <name> --add-provider <id>
    # altergo <name> --remove-provider <id> [--yes]
    # altergo <name> --default-provider <id>
    if args and args[0] in ("--add-provider", "--remove-provider", "--default-provider"):
        if account == _const._NATIVE_ACCOUNT and args[0] != "--default-provider":
            print(
                f"altergo: '{_const._NATIVE_ACCOUNT}' has no account.json and cannot manage providers.",
                file=sys.stderr,
            )
            sys.exit(1)
        if len(args) < 2 or args[1].startswith("-"):
            print(f"altergo: usage: altergo <account> {args[0]} <provider-id>", file=sys.stderr)
            sys.exit(1)
        sub, pid = args[0], args[1]
        yes = "--yes" in args[2:]
        if pid not in _const.PROVIDERS:
            print(
                f"altergo: unknown provider '{pid}'. Known: {', '.join(_const.PROVIDERS)}",
                file=sys.stderr,
            )
            sys.exit(1)
        if sub == "--add-provider":
            sys.exit(do_add_provider(account, pid))
        if sub == "--remove-provider":
            sys.exit(do_remove_provider(account, pid, assume_yes=yes))
        if sub == "--default-provider":
            if account == _const._NATIVE_ACCOUNT:
                save_native_default_provider(pid)
                print(_c(32, f"Default provider for 'native' is now '{pid}'."))
                sys.exit(0)
            sys.exit(do_default_provider(account, pid))

    # altergo [<name>] shell
    if args and args[0] == "shell":
        sys.exit(launch_shell(account))

    # altergo [<name>] portal → same as top-level portal but account already resolved
    if args and args[0] == "portal":
        p_remaining = args[1:]
        p_provider = None
        filtered = []
        for tok in p_remaining:
            if not tok.startswith("-") and tok in _const.PROVIDERS and p_provider is None:
                p_provider = tok
            else:
                filtered.append(tok)
        launch_claude(account, filtered, provider=p_provider, force_tmux=True)
        sys.exit(0)

    # 'use' subcommand removed — each account has exactly one provider
    if args and args[0] == "use":
        print(
            "altergo: 'use' subcommand has been removed.\n"
            "  Each account now has exactly one provider.\n"
            "  Create a separate account instead:\n"
            "    altergo --config <new-name> --provider <provider>",
            file=sys.stderr,
        )
        sys.exit(1)

    # altergo [<name>] -- <cmd> [args...]
    if args and args[0] == "--":
        sys.exit(launch_command(account, args[1:]))

    # Everything else → pass straight through to provider
    # altergo                    → provider (active account)
    # altergo work               → provider (work account, args=[])
    # altergo --resume x         → provider --resume x
    # altergo --dangerously-...  → provider --dangerously-...

    # Extract positional provider name if present (consumed by altergo, not passed to provider CLI)
    # Syntax: altergo <account> <provider> [args...]
    provider = None
    if args and args[0] in _const.PROVIDERS:
        provider = args[0]
        args = args[1:]

    # Final validation: if the first arg is not a provider and doesn't start with '-',
    # it might be a typo for an altergo command (e.g. 'altergo help' instead of '--help').
    if args and not args[0].startswith("-"):
        print(f"altergo: unrecognized command or provider: '{args[0]}'", file=sys.stderr)
        print("  Run 'altergo --help' for usage.", file=sys.stderr)
        sys.exit(1)

    sys.exit(launch_claude(account, args, provider=provider))


if __name__ == "__main__":
    main()
