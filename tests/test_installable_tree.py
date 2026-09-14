"""Installing the plugin must not install instructions for coding agents.

`omarchy plugin add` clones this repository into
`~/.config/omarchy/plugins/<id>/`, so every tracked file lands in a directory
that coding agents routinely operate in or below. A file named `AGENTS.md`
(or any of its siblings) is discovered and applied automatically there, which
hands whoever wrote it an instruction channel into the user's agent that the
user never opted into -- independent of whether the text happens to be benign.

Raised against tonearm in the marketplace security review of 2026-09-14,
where it blocked listing. Colophon ships the same way and is already listed,
so the exposure here was live rather than pending. The guide is now
`CONTRIBUTING.md`; this test is what stops the old name coming back, under
any of the spellings that carry the same meaning.

`git ls-files` is the right question to ask because it is exactly what a
clone produces. An untracked `AGENTS.md` in a local worktree is fine -- it is
not published.
"""

import os
import subprocess
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Filenames that a coding agent reads as instructions addressed to itself.
AGENT_INSTRUCTION_FILES = {
    "agents.md",
    "claude.md",
    "gemini.md",
    "conventions.md",
    "copilot-instructions.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".aider.conf.yml",
}


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\0") if p]


class TestNoAgentInstructionsAreShipped(unittest.TestCase):

    def test_no_tracked_file_instructs_a_coding_agent(self):
        offenders = [p for p in tracked_files()
                     if os.path.basename(p).lower() in AGENT_INSTRUCTION_FILES]
        self.assertEqual(offenders, [], "\n".join([
            "These files ship to ~/.config/omarchy/plugins/ and would be read",
            "as instructions by any coding agent working there:",
            *(f"  {p}" for p in offenders),
            "Rename to a filename that carries no agent meaning "
            "(CONTRIBUTING.md, docs/…).",
        ]))

    def test_the_contributor_guide_survived_the_rename(self):
        # The rename is only correct if the content is still there to read;
        # deleting it would also pass the test above.
        self.assertIn("CONTRIBUTING.md", tracked_files())


if __name__ == "__main__":
    unittest.main()
