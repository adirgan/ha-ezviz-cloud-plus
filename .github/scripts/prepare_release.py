"""Prepare synchronized metadata for an EZVIZ Cloud Plus release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

REPOSITORY_URL = "https://github.com/adirgan/ha-ezviz-cloud-plus"


def _update_changelog(
    path: Path, *, current_version: str, next_version: str, release_date: str
) -> str:
    """Close Unreleased and return the generated release notes."""
    changelog = path.read_text()
    unreleased = "## [Unreleased]\n"
    if unreleased not in changelog:
        raise SystemExit("CHANGELOG.md is missing the Unreleased section")

    unreleased_body = changelog.split(unreleased, 1)[1].split("\n## [", 1)[0]
    if not unreleased_body.strip():
        raise SystemExit("CHANGELOG.md Unreleased section is empty")

    release_heading = f"## [{next_version}] - {release_date}\n"
    changelog = changelog.replace(
        unreleased,
        f"{unreleased}\n{release_heading}",
        1,
    )
    unreleased_link = (
        f"[Unreleased]: {REPOSITORY_URL}/compare/v{next_version}...HEAD"
    )
    changelog = re.sub(
        r"^\[Unreleased\]: .+$",
        unreleased_link,
        changelog,
        flags=re.MULTILINE,
    )
    release_link = (
        f"[{next_version}]: {REPOSITORY_URL}/compare/"
        f"v{current_version}...v{next_version}"
    )
    changelog = changelog.replace(
        unreleased_link,
        f"{unreleased_link}\n{release_link}",
        1,
    )
    path.write_text(changelog)

    release_notes = changelog.split(release_heading, 1)[1].split(
        "\n## [", 1
    )[0].strip()
    if not release_notes:
        raise SystemExit("Generated release notes are empty")
    return release_notes


def _update_readme(path: Path, *, next_version: str) -> None:
    """Update the HACS-rendered release table."""
    readme = path.read_text()
    updated_readme, replacements = re.subn(
        r"^(\| )`\d+\.\d+\.\d+`"
        r"( \| `\d+\.\d+\.\d+` or newer"
        r" \| `\d+\.\d+\.\d+` or newer \| Active development \|)$",
        rf"\g<1>`{next_version}`\g<2>",
        readme,
        count=1,
        flags=re.MULTILINE,
    )
    if replacements != 1:
        raise SystemExit("README.md release table row was not found")
    path.write_text(updated_readme)


def main() -> None:
    """Prepare changelog, README, and GitHub release notes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("current_version")
    parser.add_argument("next_version")
    parser.add_argument("release_date")
    args = parser.parse_args()

    release_notes = _update_changelog(
        Path("CHANGELOG.md"),
        current_version=args.current_version,
        next_version=args.next_version,
        release_date=args.release_date,
    )
    _update_readme(Path("README.md"), next_version=args.next_version)
    Path("release-notes.md").write_text(
        f"# EZVIZ Cloud Plus {args.next_version}\n\n{release_notes}\n"
    )


if __name__ == "__main__":
    main()