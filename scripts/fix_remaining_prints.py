#!/usr/bin/env python3
"""Fix remaining print statements in production_readiness.py."""

import re
from pathlib import Path


def fix_production_readiness() -> None:
    """Fix all print statements in production_readiness.py."""
    file_path = Path("mahavishnu/core/production_readiness.py")
    content = file_path.read_text()

    changes = 0

    # Replace all print statements with logger calls
    # Pattern: print("text") -> logger.info("text")
    # Pattern: print(f"text") -> logger.info(f"text")

    # Info level
    patterns = [
        (r'print\("🔍 Running Production Readiness Checks\.\.\."\)', 'logger.info("Running Production Readiness Checks...")', 1),
        (r'print\("🧪 Running Integration Tests\.\.\."\)', 'logger.info("Running Integration Tests...")', 1),
        (r'print\("⚡ Running Performance Benchmarks\.\.\."\)', 'logger.info("Running Performance Benchmarks...")', 1),
        (r'print\([^\)]+f\"\\n📊 Overall Score:.*?\)', 'logger.info(f"Overall Score: {score}% ({self.checks_passed}/{self.total_checks} checks passed)")', 1),
        (r'print\([^\)]+f\"\\n📊 Test Score:.*?\)', 'logger.info(f"Test Score: {score}% ({passed_tests}/{total_tests} tests passed)")', 1),
        (r'print\([^\)]+f\"\\n📊 Performance Score:.*?\)', 'logger.info(f"Performance Score: {performance_score}/100")', 1),
        (r'print\(f\"🎯 Status: \{summary\[.summary.\]\[.status.\]\}"\)', 'logger.info(f"Status: {summary[\'summary\'][\'status\']}")', 1),

        # Success messages
        (r'print\(f\"✅ \{method\.__name__\[7:\]\.replace\(\'_\', \' \)\.title\(\)\}: PASSED\"\)',
         'logger.info(f"{method.__name__[7:].replace(\'_\', \' \').title()}: PASSED")', 1),
        (r'print\(f\"✅ \{method\.__name__\[6:\]\.replace\(\'_\', \' \)\.title\(\)\}: PASSED\"\)',
         'logger.info(f"{method.__name__[6:].replace(\'_\', \' \').title()}: PASSED")', 1),

        # Error messages
        (r'print\(f\"❌ \{method\.__name__\[7:\]\.replace\(\'_\', \' \)\.title\(\)\}: FAILED\"\)',
         'logger.error(f"{method.__name__[7:].replace(\'_\', \' \').title()}: FAILED")', 1),
        (r'print\(f\"❌ \{method\.__name__\[6:\]\.replace\(\'_\', \' \)\.title\(\)\}: FAILED\"\)',
         'logger.error(f"{method.__name__[6:].replace(\'_\', \' \').title()}: FAILED")', 1),
        (r'print\(f\"❌ \{method\.__name__\[7:\]\.replace\(\'_\', \' \)\.title\(\)\}: ERROR - \{e\}"\)',
         'logger.error(f"{method.__name__[7:].replace(\'_\', \' \').title()}: ERROR - {e}")', 1),
        (r'print\(f\"❌ \{method\.__name__\[6:\]\.replace\(\'_\', \' \)\.title\(\)\}: ERROR - \{e\}"\)',
         'logger.error(f"{method.__name__[6:].replace(\'_\', \' \').title()}: ERROR - {e}")', 1),

        # Warning messages - generic pattern
        (r'print\(\"  ⚠️  (.*)\"\)', r'logger.warning("  \1")', 100),
        (r'print\(f\"  ⚠️  (.*)\"\)', r'logger.warning(f"  \1")', 100),

        # Error messages - generic pattern
        (r'print\(\"  ❌ (.*)\"\)', r'logger.error("  \1")', 100),
        (r'print\(f\"  ❌ (.*)\"\)', r'logger.error(f"  \1")', 100),
    ]

    for pattern, replacement, max_replace in patterns:
        matches = list(re.finditer(pattern, content, re.MULTILINE | re.DOTALL))
        if matches:
            for match in matches[:max_replace]:
                old_text = match.group(0)
                new_text = replacement
                # Replace {method.__name__[7:]} patterns with actual regex groups
                if "{method.__name__" in old_text:
                    # Keep the original pattern for these complex cases
                    continue
                content = content.replace(old_text, new_text, 1)
                changes += 1

    # Now use a simpler approach - replace all remaining print statements
    lines = content.split("\n")
    new_lines = []

    for line in lines:
        if "print(" in line and "logger." not in line:
            # Extract the print content
            match = re.search(r'print\((.*)\)', line)
            if match:
                print_content = match.group(1)

                # Determine log level
                if "❌" in line or "ERROR" in line or "failed" in line.lower():
                    log_level = "error"
                elif "⚠️" in line or "Warning" in line or "CAUTION" in line:
                    log_level = "warning"
                else:
                    log_level = "info"

                # Replace print with logger call
                indent = len(line) - len(line.lstrip())
                new_line = " " * indent + f"logger.{log_level}({print_content})"
                new_lines.append(new_line)
                changes += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    content = "\n".join(new_lines)

    # Write back
    file_path.write_text(content)
    print(f"Fixed {changes} print statements in production_readiness.py")


if __name__ == "__main__":
    fix_production_readiness()
