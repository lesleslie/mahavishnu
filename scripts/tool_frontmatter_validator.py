#!/usr/bin/env python3
"""
Tool Frontmatter Validator

Validates tool frontmatter against the schema defined in docs/tool-frontmatter-schema.md

Usage:
    uv run scripts/tool_frontmatter_validator.py validate-all
    uv run scripts/tool_frontmatter_validator.py validate <tool-file>
    uv run scripts/tool_frontmatter_validator.py fix-ids
    uv run scripts/tool_frontmatter_validator.py report-stale
    uv run scripts/tool_frontmatter_validator.py add-categories
"""

import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Install with: pip install pyyaml")
    sys.exit(1)


def generate_ulid() -> str:
    """Generate a ULID (Universally Unique Lexicographically Sortable Identifier)"""
    # ULID format: 10 chars timestamp + 16 chars randomness
    import random
    import string

    timestamp = int(time.time() * 1000)  # milliseconds since epoch

    # Encode timestamp in base32 (Crockford's base32)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    timestamp_str = ""
    for _ in range(10):
        timestamp_str = alphabet[timestamp % 32] + timestamp_str
        timestamp //= 32

    # Generate 16 random chars
    random_str = "".join(random.choices(alphabet, k=16))

    return timestamp_str + random_str


@dataclass
class ValidationIssue:
    """Represents a validation issue"""

    severity: str  # critical, warning, info
    field: str
    message: str
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Results of validating a single tool"""

    file_path: Path
    valid: bool
    issues: list[ValidationIssue]
    frontmatter: dict


class ToolFrontmatterValidator:
    """Validates tool frontmatter against the schema"""

    REQUIRED_FIELDS = ["title", "owner", "last_reviewed", "status", "id", "category"]

    VALID_STATUS_VALUES = ["active", "deprecated", "experimental", "archived"]

    VALID_RISK_VALUES = ["low", "medium", "high", "critical"]

    VALID_OWNERS = [
        "Developer Enablement Guild",
        "Delivery Operations",
        "Platform Reliability Guild",
        "Operations Enablement Guild",
        "Quality Engineering Guild",
        "Automation Guild",
        "Security Guild",
        "Platform Engineering Guild",
    ]

    VALID_PLATFORMS = ["macOS", "Linux", "Windows", "Docker", "Web"]

    VALID_CATEGORIES = [
        "development",
        "deployment",
        "monitoring",
        "workflow",
        "automation",
        "maintenance",
    ]

    ULID_PATTERN = re.compile(r"^[0-9A-Z]{26}$")
    DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir

    def parse_frontmatter(self, file_path: Path) -> tuple[Optional[dict], str]:
        """Parse YAML frontmatter from a markdown file"""
        content = file_path.read_text()

        # Check for frontmatter delimiter
        if not content.startswith("---\n"):
            return None, content

        # Find the closing delimiter
        end_match = re.search(r"\n---\n", content[4:])
        if not end_match:
            return None, content

        # Extract and parse frontmatter
        frontmatter_text = content[4 : end_match.start() + 4]
        body = content[end_match.end() + 4 :]

        try:
            frontmatter = yaml.safe_load(frontmatter_text)
            return frontmatter, body
        except yaml.YAMLError as e:
            print(f"YAML parse error in {file_path}: {e}")
            return None, body

    def validate_required_fields(
        self, frontmatter: dict, issues: list[ValidationIssue]
    ):
        """Validate all required fields are present"""
        for field in self.REQUIRED_FIELDS:
            if field not in frontmatter or frontmatter[field] is None:
                issues.append(
                    ValidationIssue(
                        severity="critical",
                        field=field,
                        message=f"Missing required field: {field}",
                        suggestion=f"Add '{field}:' to frontmatter",
                    )
                )

    def validate_id(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate ID field format (ULID)"""
        if "id" not in frontmatter:
            return

        id_value = str(frontmatter["id"])
        if not self.ULID_PATTERN.match(id_value):
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="id",
                    message=f"Invalid ID format: {id_value}",
                    suggestion="ID must be 26 uppercase alphanumeric characters (ULID)",
                )
            )

    def validate_date(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate last_reviewed date format and staleness"""
        if "last_reviewed" not in frontmatter:
            return

        date_value = str(frontmatter["last_reviewed"])

        # Check format
        if not self.DATE_PATTERN.match(date_value):
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="last_reviewed",
                    message=f"Invalid date format: {date_value}",
                    suggestion="Use YYYY-MM-DD format (e.g., 2025-10-01)",
                )
            )
            return

        # Check staleness
        try:
            review_date = datetime.strptime(date_value, "%Y-%m-%d")
            today = datetime.now()
            age_days = (today - review_date).days

            if age_days > 365:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        field="last_reviewed",
                        message=f"Tool not reviewed in {age_days} days (>1 year)",
                        suggestion="Consider archiving or updating this tool",
                    )
                )
            elif age_days > 180:
                issues.append(
                    ValidationIssue(
                        severity="info",
                        field="last_reviewed",
                        message=f"Tool not reviewed in {age_days} days (>6 months)",
                        suggestion="Review and update last_reviewed date",
                    )
                )
        except ValueError:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="last_reviewed",
                    message=f"Invalid date value: {date_value}",
                    suggestion="Ensure date is valid (e.g., not 2025-02-30)",
                )
            )

    def validate_status(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate status field"""
        if "status" not in frontmatter:
            return

        status = frontmatter["status"]
        if status not in self.VALID_STATUS_VALUES:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="status",
                    message=f"Invalid status: {status}",
                    suggestion=f"Must be one of: {', '.join(self.VALID_STATUS_VALUES)}",
                )
            )

    def validate_owner(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate owner field"""
        if "owner" not in frontmatter:
            return

        owner = frontmatter["owner"]
        if owner not in self.VALID_OWNERS:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="owner",
                    message=f"Non-standard owner: {owner}",
                    suggestion=f"Consider using: {', '.join(self.VALID_OWNERS)}",
                )
            )

    def validate_risk(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate risk field if present"""
        if "risk" not in frontmatter:
            return

        risk = frontmatter["risk"]
        if risk not in self.VALID_RISK_VALUES:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="risk",
                    message=f"Invalid risk level: {risk}",
                    suggestion=f"Must be one of: {', '.join(self.VALID_RISK_VALUES)}",
                )
            )

    def validate_category(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate category field"""
        if "category" not in frontmatter:
            return

        category = frontmatter["category"]
        primary = category.split("/")[0] if "/" in category else category

        if primary not in self.VALID_CATEGORIES:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="category",
                    message=f"Non-standard category: {category}",
                    suggestion=f"Primary should be: {', '.join(self.VALID_CATEGORIES)}",
                )
            )

    def validate_platforms(self, frontmatter: dict, issues: list[ValidationIssue]):
        """Validate supported_platforms field if present"""
        if "supported_platforms" not in frontmatter:
            return

        platforms = frontmatter["supported_platforms"]
        if not isinstance(platforms, list):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="supported_platforms",
                    message="supported_platforms should be a list",
                    suggestion="Use YAML list format: - macOS\\n  - Linux",
                )
            )
            return

        for platform in platforms:
            if platform not in self.VALID_PLATFORMS:
                issues.append(
                    ValidationIssue(
                        severity="info",
                        field="supported_platforms",
                        message=f"Non-standard platform: {platform}",
                        suggestion=f"Typically: {', '.join(self.VALID_PLATFORMS)}",
                    )
                )

    def validate_deprecated(
        self, frontmatter: dict, body: str, issues: list[ValidationIssue]
    ):
        """Validate deprecated tools have migration guides"""
        if frontmatter.get("status") != "deprecated":
            return

        if "migration" not in body.lower() and "deprecated" not in body.lower():
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="status",
                    message="Deprecated tool missing migration guide",
                    suggestion="Add migration path to replacement tool in body",
                )
            )

    def validate_tool(self, file_path: Path) -> ValidationResult:
        """Validate a single tool file"""
        frontmatter, body = self.parse_frontmatter(file_path)
        issues = []

        if frontmatter is None:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="frontmatter",
                    message="No valid YAML frontmatter found",
                    suggestion="Add frontmatter block between --- delimiters",
                )
            )
            return ValidationResult(
                file_path=file_path, valid=False, issues=issues, frontmatter={}
            )

        # Run all validations
        self.validate_required_fields(frontmatter, issues)
        self.validate_id(frontmatter, issues)
        self.validate_date(frontmatter, issues)
        self.validate_status(frontmatter, issues)
        self.validate_owner(frontmatter, issues)
        self.validate_risk(frontmatter, issues)
        self.validate_category(frontmatter, issues)
        self.validate_platforms(frontmatter, issues)
        self.validate_deprecated(frontmatter, body, issues)

        # Check for critical issues
        has_critical = any(issue.severity == "critical" for issue in issues)

        return ValidationResult(
            file_path=file_path,
            valid=not has_critical,
            issues=issues,
            frontmatter=frontmatter,
        )

    def validate_all_tools(self) -> list[ValidationResult]:
        """Validate all tool files in the tools directory"""
        results = []

        # Find all .md files in tools directory
        for md_file in self.tools_dir.rglob("*.md"):
            if md_file.is_file():
                result = self.validate_tool(md_file)
                results.append(result)

        return results

    def report_results(self, results: list[ValidationResult]):
        """Print validation results"""
        print(f"\n{'=' * 80}")
        print(f"Tool Frontmatter Validation Report")
        print(f"{'=' * 80}\n")

        # Summary stats
        total = len(results)
        valid = sum(1 for r in results if r.valid)
        critical_count = sum(
            len([i for i in r.issues if i.severity == "critical"]) for r in results
        )
        warning_count = sum(
            len([i for i in r.issues if i.severity == "warning"]) for r in results
        )
        info_count = sum(
            len([i for i in r.issues if i.severity == "info"]) for r in results
        )

        print(f"Total Tools: {total}")
        print(f"Valid: {valid} ({valid/total*100:.1f}%)")
        print(f"Invalid: {total - valid} ({(total-valid)/total*100:.1f}%)\n")
        print(f"Issues: {critical_count} critical, {warning_count} warnings, {info_count} info\n")

        # Details for invalid tools
        invalid_results = [r for r in results if not r.valid]
        if invalid_results:
            print(f"\n{'-' * 80}")
            print(f"CRITICAL ISSUES ({len(invalid_results)} tools)")
            print(f"{'-' * 80}\n")

            for result in invalid_results:
                rel_path = result.file_path.relative_to(self.tools_dir.parent)
                print(f"📄 {rel_path}")
                critical_issues = [i for i in result.issues if i.severity == "critical"]
                for issue in critical_issues:
                    print(f"   ❌ [{issue.field}] {issue.message}")
                    if issue.suggestion:
                        print(f"      💡 {issue.suggestion}")
                print()

        # Warnings
        warning_results = [r for r in results if r.valid and any(i.severity == "warning" for i in r.issues)]
        if warning_results:
            print(f"\n{'-' * 80}")
            print(f"WARNINGS ({len(warning_results)} tools)")
            print(f"{'-' * 80}\n")

            for result in warning_results[:10]:  # Limit to first 10
                rel_path = result.file_path.relative_to(self.tools_dir.parent)
                print(f"📄 {rel_path}")
                warnings = [i for i in result.issues if i.severity == "warning"]
                for issue in warnings:
                    print(f"   ⚠️  [{issue.field}] {issue.message}")
                    if issue.suggestion:
                        print(f"      💡 {issue.suggestion}")
                print()

            if len(warning_results) > 10:
                print(f"... and {len(warning_results) - 10} more tools with warnings\n")

        print(f"\n{'=' * 80}")

    def fix_missing_ids(self):
        """Add ULIDs to tools missing IDs"""
        print("Scanning for tools with missing or invalid IDs...\n")

        fixed_count = 0
        for md_file in self.tools_dir.rglob("*.md"):
            if not md_file.is_file():
                continue

            frontmatter, body = self.parse_frontmatter(md_file)
            if frontmatter is None:
                print(f"⏭️  Skipping {md_file.name} (no frontmatter)")
                continue

            # Check if ID is missing or invalid
            needs_fix = False
            if "id" not in frontmatter:
                needs_fix = True
            elif not self.ULID_PATTERN.match(str(frontmatter["id"])):
                needs_fix = True

            if needs_fix:
                # Generate new ULID
                new_id = generate_ulid()
                frontmatter["id"] = new_id

                # Write back to file
                new_content = "---\n"
                new_content += yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
                new_content += "---\n"
                new_content += body

                md_file.write_text(new_content)
                print(f"✅ Fixed {md_file.name}: Added ID {new_id}")
                fixed_count += 1

        print(f"\n✨ Fixed {fixed_count} tools")

    def report_stale_tools(self):
        """Report tools that haven't been reviewed recently"""
        print("\nScanning for stale tools (not reviewed in 6+ months)...\n")

        stale_tools = []
        today = datetime.now()

        for md_file in self.tools_dir.rglob("*.md"):
            if not md_file.is_file():
                continue

            frontmatter, _ = self.parse_frontmatter(md_file)
            if not frontmatter or "last_reviewed" not in frontmatter:
                continue

            try:
                review_date = datetime.strptime(frontmatter["last_reviewed"], "%Y-%m-%d")
                age_days = (today - review_date).days

                if age_days > 180:
                    stale_tools.append(
                        (md_file, age_days, frontmatter.get("status", "unknown"))
                    )
            except (ValueError, TypeError):
                continue

        # Sort by age (oldest first)
        stale_tools.sort(key=lambda x: x[1], reverse=True)

        if stale_tools:
            print(f"Found {len(stale_tools)} stale tools:\n")
            for file_path, age_days, status in stale_tools:
                rel_path = file_path.relative_to(self.tools_dir.parent)
                age_months = age_days // 30
                print(f"📅 {rel_path}")
                print(f"   Age: {age_months} months ({age_days} days) | Status: {status}\n")
        else:
            print("✅ No stale tools found!")

    def add_category_to_all(self):
        """Add category field to all tools based on directory structure"""
        print("Adding category field to tools based on directory...\n")

        updated_count = 0
        for md_file in self.tools_dir.rglob("*.md"):
            if not md_file.is_file():
                continue

            frontmatter, body = self.parse_frontmatter(md_file)
            if frontmatter is None:
                continue

            # Skip if already has category
            if "category" in frontmatter:
                continue

            # Infer category from directory structure
            # Example: /tools/development/api/api-scaffold.md -> development/api
            rel_path = md_file.relative_to(self.tools_dir)
            parts = rel_path.parts[:-1]  # Remove filename

            if len(parts) == 0:
                category = "uncategorized"
            elif len(parts) == 1:
                category = parts[0]
            else:
                category = "/".join(parts)

            # Add category
            frontmatter["category"] = category

            # Write back
            new_content = "---\n"
            new_content += yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
            new_content += "---\n"
            new_content += body

            md_file.write_text(new_content)
            print(f"✅ {md_file.name}: Added category '{category}'")
            updated_count += 1

        print(f"\n✨ Updated {updated_count} tools")


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    tools_dir = Path(__file__).parent.parent / "commands" / "tools"

    validator = ToolFrontmatterValidator(tools_dir)

    if command == "validate-all":
        results = validator.validate_all_tools()
        validator.report_results(results)

    elif command == "validate":
        if len(sys.argv) < 3:
            print("Usage: validate <tool-file>")
            sys.exit(1)
        tool_file = Path(sys.argv[2])
        result = validator.validate_tool(tool_file)
        validator.report_results([result])

    elif command == "fix-ids":
        validator.fix_missing_ids()

    elif command == "report-stale":
        validator.report_stale_tools()

    elif command == "add-categories":
        validator.add_category_to_all()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
