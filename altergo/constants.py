import os
import pwd
from pathlib import Path

_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
MAIN_CLAUDE = MAIN_HOME / ".claude"
ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"

_NATIVE_ACCOUNT = "native"

_RESERVED_NAMES = frozenset(
    [
        "main",
        "list",
        "new",
        "rm",
        "shell",
        "config",
        "setup",
        "teardown",
        "help",
        "version",
        "legacy",
        "backup",
        "migrate",
        "use",
        "native",
    ]
)

SETTINGS_FILE = MAIN_HOME / ".altergo" / ".altergo.json"
STARRED_FILE = MAIN_HOME / ".altergo" / "starred.json"
LAST_SESSION_FILE = MAIN_HOME / ".altergo" / "last_session.json"

SYMLINK_DIRS = [
    "projects",
    "tasks",
    "session-env",
    "file-history",
    "shell-snapshots",
    "agents",
    "commands",
    "skills",
    "plans",
    "cache",
]

SYMLINK_FILES = [
    "settings.json",
    "CLAUDE.md",
    "keybindings.json",
]

PROVIDERS = {
    "claude": {
        "display_name": "Claude Code",
        "dot_dir": ".claude",
        "binary": "claude",
        "credentials_file": ".credentials.json",
        "symlink_dirs": [
            "projects",
            "tasks",
            "session-env",
            "file-history",
            "shell-snapshots",
            "agents",
            "commands",
            "skills",
            "plans",
            "cache",
        ],
        "symlink_files": ["settings.json", "CLAUDE.md", "keybindings.json"],
        "flags": {
            "skip_perms": ["--dangerously-skip-permissions"],
            "resume_last": ["--continue"],
            "resume_by_id": ["--resume", "{id}"],
        },
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "dot_dir": ".gemini",
        "binary": "gemini",
        "credentials_file": "oauth_creds.json",
        "symlink_dirs": ["tmp", "commands"],
        "symlink_files": ["settings.json", "GEMINI.md"],
        "flags": {
            "skip_perms": ["--yolo"],
            "resume_last": ["--resume", "latest"],
            "resume_by_id": ["--resume", "{id}"],
        },
    },
    "codex": {
        "display_name": "Codex CLI",
        "dot_dir": ".codex",
        "binary": "codex",
        "credentials_file": "auth.json",
        "symlink_dirs": ["sessions", "rules"],
        "symlink_files": ["config.toml", "AGENTS.md", "AGENTS.override.md"],
        "flags": {
            "skip_perms": ["--dangerously-bypass-approvals-and-sandbox"],
            "resume_subcommand": ["resume", "--last"],
            "resume_by_id_subcommand": ["resume", "{id}"],
        },
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "dot_dir": ".copilot",
        "binary": "copilot",
        "credentials_file": "config.json",
        "symlink_dirs": ["session-state", "agents", "skills", "hooks"],
        "symlink_files": ["mcp-config.json", "lsp-config.json"],
        "flags": {
            "skip_perms": ["--yolo", "--autopilot"],
            "resume_last": ["--continue"],
            "resume_by_id": ["--resume", "{id}"],
        },
    },
}

CATALOG = [
    # Cloud Providers
    {
        "id": "aws",
        "name": "AWS CLI",
        "category": "Cloud Providers",
        "paths": [".aws"],
        "default_on": True,
    },
    {
        "id": "gcloud",
        "name": "Google Cloud",
        "category": "Cloud Providers",
        "paths": [".config/gcloud"],
        "default_on": True,
    },
    {
        "id": "azure",
        "name": "Azure CLI",
        "category": "Cloud Providers",
        "paths": [".azure", ".config/azure"],
        "default_on": True,
    },
    # Containers & Orchestration
    {
        "id": "docker",
        "name": "Docker",
        "category": "Containers",
        "paths": [".docker"],
        "default_on": True,
    },
    {
        "id": "kube",
        "name": "Kubernetes",
        "category": "Containers",
        "paths": [".kube"],
        "default_on": True,
    },
    # Infrastructure
    {
        "id": "terraform",
        "name": "Terraform",
        "category": "Infrastructure",
        "paths": [".terraform.d"],
        "default_on": True,
    },
    # VCS & Dev Tools
    {
        "id": "gh",
        "name": "GitHub CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/gh"],
        "default_on": True,
    },
    {
        "id": "glab",
        "name": "GitLab CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/glab"],
        "default_on": False,
    },
    # Package Managers
    {
        "id": "npm",
        "name": "npm",
        "category": "Package Managers",
        "paths": [".npmrc"],
        "default_on": False,
    },
    {
        "id": "pip",
        "name": "pip (Python)",
        "category": "Package Managers",
        "paths": [".pip", ".config/pip", ".pypirc", ".local/lib", ".local/bin"],
        "default_on": False,
        "warning": "Shares pip config, PyPI credentials, and user-installed packages/scripts (~/.local/lib & bin).",
    },
    {
        "id": "cargo",
        "name": "cargo (Rust)",
        "category": "Package Managers",
        "paths": [".cargo"],
        "default_on": False,
        "warning": "Shares the entire ~/.cargo dir: registry cache, installed binaries, and credentials.",
    },
    {
        "id": "gem",
        "name": "gem (Ruby)",
        "category": "Package Managers",
        "paths": [".gem", ".gemrc"],
        "default_on": False,
    },
    {
        "id": "yarn",
        "name": "yarn",
        "category": "Package Managers",
        "paths": [".yarn", ".yarnrc.yml", ".yarnrc"],
        "default_on": False,
    },
    {
        "id": "pnpm",
        "name": "pnpm",
        "category": "Package Managers",
        "paths": [".pnpmrc", ".local/share/pnpm"],
        "default_on": False,
    },
    {
        "id": "composer",
        "name": "composer (PHP)",
        "category": "Package Managers",
        "paths": [".composer"],
        "default_on": False,
        "warning": "Shares Composer auth tokens, config, and globally installed packages.",
    },
    {
        "id": "go",
        "name": "go modules",
        "category": "Package Managers",
        "paths": ["go", ".config/go"],
        "default_on": False,
        "warning": "Shares the Go module cache (~/go) and go env config. Can be large.",
    },
    {
        "id": "maven",
        "name": "Maven (Java)",
        "category": "Package Managers",
        "paths": [".m2"],
        "default_on": False,
        "warning": "Shares the ~/.m2 directory including settings.xml credentials and local repo cache.",
    },
    {
        "id": "gradle",
        "name": "Gradle (Java)",
        "category": "Package Managers",
        "paths": [".gradle"],
        "default_on": False,
    },
    {
        "id": "bundler",
        "name": "Bundler (Ruby)",
        "category": "Package Managers",
        "paths": [".bundle"],
        "default_on": False,
    },
    # Identity — off by default, high security/identity impact
    {
        "id": "ssh",
        "name": "SSH keys",
        "category": "Identity",
        "paths": [".ssh"],
        "default_on": False,
        "warning": "Shares SSH keys & known_hosts. Keep off if you use per-identity SSH keys.",
    },
    {
        "id": "gitconfig",
        "name": "Git identity",
        "category": "Identity",
        "paths": [".gitconfig"],
        "default_on": False,
        "warning": "Shares git user.name/email. Keep off for separate commit identity per account.",
    },
    {
        "id": "gnupg",
        "name": "GPG keys",
        "category": "Identity",
        "paths": [".gnupg"],
        "default_on": False,
        "warning": "Shares GPG keyring. Keep off if you use per-identity signing keys.",
    },
]
