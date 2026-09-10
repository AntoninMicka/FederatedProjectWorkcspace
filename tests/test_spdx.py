# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

CHECKED_SUFFIXES = {
    ".py",
    ".sh",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".toml",
    ".md",
}

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "vendor",
    "third_party",
    "dist",
    "build",
}

EXCLUDED_PATHS = {
    Path("LICENSE"),
    Path("REUSE_CATALOG.private.md"),
}

EXCLUDED_PREFIXES = (
    Path("docs/legal/licenses"),
)

MAX_HEADER_BYTES = 8192


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)

    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True

    if relative in EXCLUDED_PATHS:
        return True

    if any(
        relative == prefix or prefix in relative.parents
        for prefix in EXCLUDED_PREFIXES
    ):
        return True

    return False


def files_requiring_spdx():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in CHECKED_SUFFIXES:
            continue

        if is_excluded(path):
            continue

        yield path


class SPDXTests(unittest.TestCase):

    def test_project_text_files_have_spdx_metadata(self):
        missing = []

        for path in files_requiring_spdx():
            try:
                with path.open("r", encoding="utf-8", errors="strict") as handle:
                    header_lines = []

                    for _ in range(100):
                        line = handle.readline()

                        if not line:
                            break

                        header_lines.append(line)

                    header = "".join(header_lines)
            except UnicodeDecodeError:
                self.fail(
                    f"Expected project text file is not valid UTF-8: "
                    f"{path.relative_to(ROOT)}"
                )

            problems = []

            if "SPDX-FileCopyrightText:" not in header:
                problems.append("SPDX-FileCopyrightText")

            if "SPDX-License-Identifier:" not in header:
                problems.append("SPDX-License-Identifier")

            if problems:
                missing.append(
                    f"{path.relative_to(ROOT)}: missing "
                    + ", ".join(problems)
                )

        self.assertFalse(
            missing,
            "Files without required SPDX metadata:\n"
            + "\n".join(f"  - {item}" for item in missing),
        )


if __name__ == "__main__":
    unittest.main()