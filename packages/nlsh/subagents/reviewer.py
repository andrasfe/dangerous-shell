"""ScriptReviewer subagent - analyzes scripts for safety and correctness."""

import re
from typing import Any

from .base import BaseSubagent
from ..script_types import (
    GeneratedScript,
    ScriptReview,
    RiskLevel,
)


# Patterns to detect dangerous operations
# (pattern, risk_level, description)
DANGEROUS_PATTERNS: list[tuple[str, RiskLevel, str]] = [
    # Critical - immediate rejection
    (r'\brm\s+-[rfR]*\s+/', RiskLevel.CRITICAL, "Recursive delete from root"),
    (r'\brm\s+-[rfR]*\s+\*', RiskLevel.CRITICAL, "Recursive delete with wildcard"),
    (r'>\s*/dev/(sd[a-z]|nvme|hd[a-z])', RiskLevel.CRITICAL, "Direct device write"),
    (r'\bcurl\s+.*\|\s*(sudo\s+)?bash', RiskLevel.CRITICAL, "Remote code execution via curl"),
    (r'\bwget\s+.*\|\s*(sudo\s+)?bash', RiskLevel.CRITICAL, "Remote code execution via wget"),
    (r'\bmkfs\b', RiskLevel.CRITICAL, "Filesystem format command"),

    # Dangerous - require explicit confirmation
    (r'\brm\s+-[rfR]', RiskLevel.DANGEROUS, "Recursive or force delete"),
    (r'\bdd\s+if=', RiskLevel.DANGEROUS, "Direct disk write with dd"),
    (r'\bsudo\s+rm\b', RiskLevel.DANGEROUS, "Root deletion"),
    (r'\bsudo\s+dd\b', RiskLevel.DANGEROUS, "Root disk operation"),
    (r'\bsudo\s+chmod\b', RiskLevel.DANGEROUS, "Root permission change"),
    (r'\bsudo\s+chown\b', RiskLevel.DANGEROUS, "Root ownership change"),
    (r'>\s*/etc/', RiskLevel.DANGEROUS, "Writing to /etc"),
    (r'>\s*/usr/', RiskLevel.DANGEROUS, "Writing to /usr"),
    (r'\bkill\s+-9\b', RiskLevel.DANGEROUS, "Force kill process"),
    (r'\bpkill\b', RiskLevel.DANGEROUS, "Pattern-based process kill"),
    (r'\breboot\b', RiskLevel.DANGEROUS, "System reboot"),
    (r'\bshutdown\b', RiskLevel.DANGEROUS, "System shutdown"),
    (r'\bsystemctl\s+(stop|restart|disable)', RiskLevel.DANGEROUS, "Service control"),

    # Moderate - warn but allow
    (r'\bsudo\b', RiskLevel.MODERATE, "Elevated privileges"),
    (r'\bchmod\s+.*777', RiskLevel.MODERATE, "World-writable permissions"),
    (r'\bchmod\s+-R', RiskLevel.MODERATE, "Recursive permission change"),
    (r'\beval\s+', RiskLevel.MODERATE, "Dynamic code evaluation"),
    (r'\$\(.*\)', RiskLevel.MODERATE, "Command substitution"),
    (r'`.*`', RiskLevel.MODERATE, "Backtick command substitution"),
    (r'\bexport\s+PATH=', RiskLevel.MODERATE, "PATH modification"),
    (r'\bsource\b', RiskLevel.MODERATE, "Sourcing external script"),
    (r'\.\s+/', RiskLevel.MODERATE, "Sourcing external script"),
]

# Patterns that indicate good practices
GOOD_PRACTICES = [
    (r'^set\s+-[euo]', "Uses strict error handling"),
    (r'\btrap\b.*ERR', "Has error trap handler"),
    (r'\$\{[A-Z_]+:-', "Uses variable defaults"),
    (r'\[\[\s+', "Uses modern test syntax"),
    (r'#.*[A-Z]', "Has comments"),
]


class ScriptReviewer(BaseSubagent[ScriptReview]):
    """Reviews shell scripts for safety and correctness.

    Analyzes scripts for:
    - Dangerous commands (rm -rf, dd, etc.)
    - Security issues (curl | bash, eval, etc.)
    - Best practices (error handling, quoting, etc.)
    """

    def __init__(self):
        """Initialize the script reviewer."""
        super().__init__("ScriptReviewer")

    async def process(
        self,
        script: GeneratedScript,
    ) -> ScriptReview:
        """Review a generated script for safety and correctness.

        Args:
            script: The GeneratedScript to review

        Returns:
            ScriptReview with approval status and any warnings
        """
        warnings: list[str] = []
        dangerous_ops: list[tuple[int, str]] = []
        suggestions: list[str] = []
        max_risk = RiskLevel.SAFE

        lines = script.script.split('\n')

        # Check each line for dangerous patterns
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            for pattern, risk, description in DANGEROUS_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    dangerous_ops.append((line_num, description))
                    if self._risk_value(risk) > self._risk_value(max_risk):
                        max_risk = risk
                    if risk == RiskLevel.CRITICAL:
                        warnings.append(f"CRITICAL: {description} (line {line_num})")
                    elif risk == RiskLevel.DANGEROUS:
                        warnings.append(f"Dangerous: {description} (line {line_num})")

        # Check for missing best practices
        script_text = script.script
        has_error_handling = bool(re.search(r'set\s+-[euo]', script_text))
        has_trap = bool(re.search(r'\btrap\b', script_text))
        has_shebang = script_text.strip().startswith('#!')

        if not has_shebang:
            suggestions.append("Add shebang (#!/usr/bin/env bash)")
        if not has_error_handling:
            suggestions.append("Add 'set -euo pipefail' for strict error handling")
        if not has_trap:
            suggestions.append("Consider adding error trap handler")

        # Check for unquoted variables
        unquoted = re.findall(r'\$[A-Za-z_][A-Za-z0-9_]*(?!["\'])', script_text)
        if unquoted:
            suggestions.append(f"Consider quoting variables: {', '.join(set(unquoted[:3]))}")

        # Determine approval
        approved = max_risk != RiskLevel.CRITICAL

        # Upgrade risk level if generator said safe but we found issues
        if max_risk == RiskLevel.SAFE and len(dangerous_ops) > 0:
            max_risk = RiskLevel.MODERATE

        return ScriptReview(
            approved=approved,
            risk_level=max_risk,
            warnings=warnings,
            dangerous_ops=dangerous_ops,
            suggestions=suggestions,
        )

    def _risk_value(self, risk: RiskLevel) -> int:
        """Get numeric value for risk level comparison."""
        return {
            RiskLevel.SAFE: 0,
            RiskLevel.MODERATE: 1,
            RiskLevel.DANGEROUS: 2,
            RiskLevel.CRITICAL: 3,
        }[risk]

    def get_risk_emoji(self, risk: RiskLevel) -> str:
        """Get emoji representation of risk level."""
        return {
            RiskLevel.SAFE: "✅",
            RiskLevel.MODERATE: "⚠️",
            RiskLevel.DANGEROUS: "🔶",
            RiskLevel.CRITICAL: "🚫",
        }[risk]

    def format_review(self, review: ScriptReview) -> str:
        """Format a review for terminal display.

        Args:
            review: The ScriptReview to format

        Returns:
            Formatted string for display
        """
        lines = []
        emoji = self.get_risk_emoji(review.risk_level)
        lines.append(f"Risk Level: {emoji} {review.risk_level.value.upper()}")

        if review.warnings:
            lines.append("\nWarnings:")
            for warning in review.warnings:
                lines.append(f"  • {warning}")

        if review.dangerous_ops:
            lines.append("\nDangerous Operations:")
            for line_num, desc in review.dangerous_ops:
                lines.append(f"  Line {line_num}: {desc}")

        if review.suggestions:
            lines.append("\nSuggestions:")
            for suggestion in review.suggestions:
                lines.append(f"  • {suggestion}")

        if not review.approved:
            lines.append("\n🚫 Script REJECTED due to critical safety issues")
        elif review.risk_level == RiskLevel.DANGEROUS:
            lines.append("\n⚠️ Script requires explicit confirmation")

        return "\n".join(lines)
