"""Optional private literal terms kept outside the product checkout.

Set VIBE_PRIVACY_TERMS_FILE or the clone-local privacy.termsFile Git setting.
The UTF-8 file has one literal per nonempty line. Matching is case-insensitive.
An explicitly configured unreadable, empty or in-tree policy fails closed.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def load_terms(root: Path) -> tuple[str, ...]:
    selected = os.environ.get("VIBE_PRIVACY_TERMS_FILE")
    if selected is None:
        result = subprocess.run(["git", "-C", str(root), "config", "--local", "--get", "privacy.termsFile"],
                                capture_output=True, text=True, check=False)
        if result.returncode not in (0, 1):
            raise ValueError("cannot read private-policy configuration")
        selected = result.stdout.strip() if result.returncode == 0 else None
    if selected is None:
        return ()
    if not selected or not Path(selected).is_absolute():
        raise ValueError("configured private-policy file needs an absolute external path")
    try:
        supplied = Path(selected)
        path = supplied.resolve(strict=True)
        if path.is_relative_to(root.resolve()):
            raise ValueError("private-policy file must be outside the source checkout")
        # Check both names: neither a symlink into Git nor a symlink out of
        # a checkout is an external configuration interface. Include other
        # worktrees, linked-worktree markers and bare object stores.
        for candidate in (supplied, path):
            for parent in candidate.parents:
                marker = parent / ".git"
                if (parent.name.casefold() == ".git" or marker.exists()
                        or marker.is_symlink()
                        or ((parent / "HEAD").is_file()
                            and (parent / "objects").is_dir()
                            and (parent / "refs").is_dir())):
                    raise ValueError("private-policy file must be outside Git repositories and object stores")
        terms = tuple(line.strip().casefold() for line in path.read_text(encoding="utf-8").splitlines()
                      if line.strip())
    except (OSError, UnicodeError) as error:
        raise ValueError("configured private-policy file cannot be read") from error
    if not terms:
        raise ValueError("configured private-policy file has no terms")
    return terms


def matches_private_term(text: str, root: Path) -> bool:
    folded = text.casefold()
    return any(term in folded for term in load_terms(root))


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    try:
        if matches_private_term(sys.stdin.read(), root):
            print("ERROR: staged content contains private-policy matches [values redacted].", file=sys.stderr)
            return 1
    except ValueError as error:
        print(f"ERROR: {error}; private values and paths redacted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
