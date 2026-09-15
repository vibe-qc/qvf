"""Exercise the real staged-content hook in isolated disposable repositories."""

import os
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(os.environ.get("PRIVACY_HOOKS_DIR", Path(__file__).resolve().parent))


def home_path(user):
    # Synthetic input assembled at runtime; no author's home path is stored.
    return "/" + "Users/" + user + "/example"


class PrivacyHookTests(unittest.TestCase):
    def check_staged(self, content, expected, policy=None, local=False):
        with tempfile.TemporaryDirectory(prefix="privacy-hook-") as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            shutil.copytree(
                HOOKS, repo / ".githooks", ignore=shutil.ignore_patterns("__pycache__")
            )
            (repo / "example.txt").write_text(content + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "example.txt"], check=True)
            env = os.environ.copy()
            env.pop("VIBE_PRIVACY_TERMS_FILE", None)
            if policy is not None:
                policy_path = repo / "private-terms" if policy == "in-tree" else repo.parent / (repo.name + ".private-terms")
                if policy != "missing":
                    policy_path.write_text(policy)
                self.addCleanup(policy_path.unlink, missing_ok=True)
                if local:
                    subprocess.run(["git", "-C", str(repo), "config", "--local", "privacy.termsFile", str(policy_path)], check=True)
                else:
                    env["VIBE_PRIVACY_TERMS_FILE"] = str(policy_path)
            result = subprocess.run(
                ["sh", str(repo / ".githooks/pre-commit")],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode == 0, expected, result.stderr)
            return result

    def test_documented_placeholders_are_allowed(self):
        self.check_staged(
            " ".join(
                home_path(user) for user in ("USER", "Shared", "runner", "root", "user")
            ),
            True,
        )

    def test_personal_path_is_blocked(self):
        self.check_staged(home_path("private-fixture"), False)

    def test_uppercase_personal_path_is_blocked(self):
        self.check_staged(home_path("PrivateFixture"), False)

    def test_allowed_path_does_not_hide_another_match(self):
        self.check_staged(
            home_path("runner") + " " + home_path("private-fixture"), False
        )

    def test_source_line_starting_with_plus_is_checked(self):
        self.check_staged("+ " + home_path("private-fixture"), False)

    def test_allowed_username_prefix_is_not_an_exception(self):
        self.check_staged(home_path("runner-private"), False)

    def test_diagnostics_do_not_repeat_the_private_value(self):
        private = home_path("private-fixture")
        result = self.check_staged(private, False)
        self.assertNotIn(private, result.stderr)
        self.assertIn("redacted", result.stderr)

    @unittest.skipUnless(
        "PRIVATE_IP_PATTERN=" in (HOOKS / "pre-commit").read_text(),
        "no address rule in this repository",
    )
    def test_rfc1918_addresses_are_not_example_exceptions(self):
        for prefix in ((10, 0, 0), (192, 168, 1), (172, 31, 4)):
            with self.subTest(prefix=prefix):
                self.check_staged(".".join(map(str, (*prefix, 9))), False)
        self.check_staged("192.0.2.9 198.51.100.9 203.0.113.9", True)

    def test_external_private_terms_are_blocked_and_redacted(self):
        term = "private-policy-fixture"
        result = self.check_staged(home_path("runner") + " " + term.upper(), False, term)
        self.assertNotIn(term, result.stderr.lower())
        self.check_staged("portable example", True, term)

    def test_clone_local_policy_uses_the_same_rules(self):
        self.check_staged("private-policy-fixture", False, "private-policy-fixture", local=True)
        self.check_staged("portable example", True, "private-policy-fixture", local=True)
        self.check_staged("portable example", False, "", local=True)

    def test_missing_or_empty_configured_policy_fails_closed(self):
        for policy in ("missing", "", "in-tree"):
            with self.subTest(policy=policy):
                self.check_staged("portable example", False, policy)

    def test_policy_rejects_other_repositories_and_symlink_interfaces(self):
        spec = importlib.util.spec_from_file_location("private_terms", HOOKS / "private_terms.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="privacy-locations-") as temporary:
            base = Path(temporary).resolve()
            root = base / "source"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            external = base / "private-terms"
            external.write_text("private-policy-fixture\n")
            other = base / "other"
            subprocess.run(["git", "init", "-q", str(other)], check=True)
            linked = base / "linked"
            linked.mkdir()
            (linked / ".git").write_text("gitdir: ../other/.git/worktrees/linked\n")
            bare = base / "objects-store"
            subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
            blocked = []
            for directory in (other, other / ".git", linked, bare):
                policy = directory / "private-terms"
                policy.write_text("private-policy-fixture\n")
                blocked.append(policy)
            into = base / "link-into-repository"
            into.symlink_to(blocked[0])
            outward = other / "link-to-external"
            outward.symlink_to(external)
            blocked.extend((into, outward))
            for policy in blocked:
                with self.subTest(location=policy.relative_to(base)):
                    with patch.dict(os.environ, {"VIBE_PRIVACY_TERMS_FILE": str(policy)}):
                        with self.assertRaisesRegex(ValueError, "outside Git"):
                            module.load_terms(root)
            with patch.dict(os.environ, {"VIBE_PRIVACY_TERMS_FILE": str(external)}):
                self.assertEqual(module.load_terms(root), ("private-policy-fixture",))



if __name__ == "__main__":
    unittest.main()
