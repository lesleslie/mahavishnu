---
title: Multi-Stage Code Review
category: workflow/
status: active
---

# Multi-Stage Code Review Workflow

This workflow implements **AI-Assisted Multi-Stage Code Review** using four specialized review agents to provide comprehensive quality assessment.

## Overview

Traditional code review often focuses on functionality and style. This workflow extends review to four critical dimensions:

1. **Security**: Vulnerabilities, injection attacks, authentication issues
2. **Performance**: Algorithmic complexity, bottlenecks, resource usage
3. **Test Coverage**: Untested code paths, edge cases, coverage gaps
4. **Documentation**: Docstrings, comments, API completeness

## When to Use

Use this workflow when:
- Reviewing pull requests before merge
- Performing deep-dive code quality assessment
- Reviewing critical security or performance-sensitive code
- Onboarding new developers (teaching review standards)

## Workflow Phases

### Phase 1: Security Review
**Agent**: `security-review-specialist` (Sonnet)

**Purpose**: Identify security vulnerabilities and compliance issues

**Actions**:
1. Review code changes for OWASP Top 10 vulnerabilities
2. Check for injection attacks (SQL, XSS, command injection)
3. Verify authentication and authorization logic
4. Examine data handling and encryption
5. Review dependencies for known vulnerabilities

**Output**: Security review report with:
- Critical issues (fix immediately)
- High/moderate/low priority findings
- Positive security practices
- Security score (1-10)

### Phase 2: Performance Review
**Agent**: `performance-review-specialist` (Sonnet)

**Purpose**: Identify performance bottlenecks and optimization opportunities

**Actions**:
1. Analyze algorithmic complexity
2. Check database queries for N+1 problems
3. Review memory management and potential leaks
4. Examine I/O operations for blocking calls
5. Identify caching opportunities

**Output**: Performance review report with:
- Critical performance issues
- Optimization opportunities
- Resource usage concerns
- Performance score (1-10)

### Phase 3: Test Coverage Review
**Agent**: `test-coverage-review-specialist` (Sonnet)

**Purpose**: Ensure comprehensive test coverage and quality

**Actions**:
1. Verify new code is covered by tests (target 80%+)
2. Check for untested edge cases and error paths
3. Review test assertion quality
4. Identify test duplication and brittleness
5. Verify integration tests for critical flows

**Output**: Test coverage review report with:
- Critical coverage gaps
- Test quality issues
- Missing edge cases
- Test score (1-10)

### Phase 4: Documentation Review
**Agent**: `documentation-review-specialist` (Haiku)

**Purpose**: Ensure complete, clear documentation

**Actions**:
1. Verify all public APIs have docstrings
2. Check docstrings follow standards (Google, JSDoc, etc.)
3. Review comments for "why" not "what"
4. Verify type hints are present and accurate
5. Check README and examples are updated

**Output**: Documentation review report with:
- Critical documentation gaps
- Quality issues
- Examples and improvements
- Documentation score (1-10)

### Phase 5: Aggregate Report
**Agent**: `code-reviewer` (Sonnet)

**Purpose**: Compile findings into prioritized action plan

**Actions**:
1. Collect all four review reports
2. Remove duplicates and consolidate findings
3. Prioritize by severity and impact
4. Create unified action plan
5. Provide overall quality assessment

**Output**: Comprehensive review report with:
- **Executive Summary**: Overall assessment and key metrics
- **Critical Findings**: Must-fix before merge
- **High Priority**: Should fix soon
- **Moderate Priority**: Consider for next sprint
- **Low Priority**: Technical debt backlog
- **Positive Highlights**: What's done well
- **Recommendations**: Prioritized action items

## How to Use

### Option 1: Interactive Workflow

Trigger this workflow when reviewing a PR:

```bash
/workflows:multi-stage-code-review
```

Then provide:
- Pull request number or commit range
- Any specific concerns or focus areas

### Option 2: Direct Agent Invocation

Invoke each review agent sequentially:

```
Please review this PR for security issues using the security-review-specialist agent.
Please review this PR for performance issues using the performance-review-specialist agent.
Please review this PR for test coverage using the test-coverage-review-specialist agent.
Please review this PR for documentation quality using the documentation-review-specialist agent.
```

Finally, aggregate the results.

### Option 3: Automated (Future)

Configure hooks in `settings.json` to automatically trigger this workflow on PR creation:

```json
{
  "hooks": {
    "PullRequestCreated:after": [
      "/workflows:multi-stage-code-review"
    ]
  }
}
```

## Expected Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Security Review | 5-10 min | Depends on code complexity |
| Performance Review | 5-10 min | Depends on code complexity |
| Test Coverage Review | 5-10 min | Depends on test files |
| Documentation Review | 3-5 min | Haiku is fast |
| Aggregation | 2-3 min | Code-reviewer synthesis |
| **Total** | **20-38 min** | For typical PR |

## Output Format

Each phase produces a structured report. Here's an example of the final aggregated report:

```markdown
# Code Review Report: PR #123 - Add user authentication

## Executive Summary

**Overall Quality Score**: 7.5/10

This PR implements user authentication with OAuth2. The implementation is solid with good test coverage and documentation. However, there are **2 critical security issues** and **1 critical performance issue** that must be addressed before merge.

**Scores by Dimension**:
- Security: 6/10 (critical issues present)
- Performance: 7/10 (one bottleneck)
- Test Coverage: 9/10 (excellent coverage)
- Documentation: 8/10 (comprehensive but missing examples)

## Critical Findings (Must Fix Before Merge)

### 1. SQL Injection Vulnerability
- **Location**: `src/auth/login.py:45`
- **Severity**: CRITICAL
- **Agent**: security-review-specialist
- **Issue**: User input directly interpolated into SQL query
- **Fix**: Use parameterized query
- **Example**:
  ```python
  - query = f"SELECT * FROM users WHERE username = '{username}'"
  + query = "SELECT * FROM users WHERE username = ?"
  + db.execute(query, [username])
  ```

### 2. Missing Rate Limiting on Login Endpoint
- **Location**: `src/auth/login.py:23`
- **Severity**: CRITICAL
- **Agent**: security-review-specialist
- **Issue**: No rate limiting allows brute force attacks
- **Fix**: Implement rate limiting using `@limiter` decorator

### 3. N+1 Database Query in User Profile
- **Location**: `src/api/users.py:78`
- **Severity**: HIGH
- **Agent**: performance-review-specialist
- **Issue**: Query inside loop causes N+1 problem
- **Fix**: Use eager loading with `joinedload()`

## High Priority Findings (Should Fix Soon)

[Additional findings...]

## Positive Highlights

- ✅ Excellent test coverage (92% line coverage)
- ✅ Comprehensive docstrings with examples
- ✅ Proper error handling in authentication flow
- ✅ Good separation of concerns

## Recommendations

1. **Immediately**: Fix SQL injection and add rate limiting
2. **This week**: Resolve N+1 query issue
3. **Next sprint**: Add integration tests for OAuth flow
4. **Technical debt**: Consider adding request caching for profile lookups

## Files Reviewed

- `src/auth/login.py` (+150 lines)
- `src/auth/oauth.py` (+200 lines)
- `src/api/users.py` (+50 lines)
- `tests/test_auth.py` (+180 lines)
```

## Integration with Crackerjack

This workflow can be integrated with Crackerjack for automated quality gates:

1. **Pre-commit**: Run quick checks (linting, basic tests)
2. **Pre-push**: Run this multi-stage review
3. **Pre-merge**: Full CI pipeline including all reviews
4. **Scheduled**: Nightly deep-dive reviews

## Success Criteria

A successful multi-stage review should:

- ✅ Identify all critical security vulnerabilities
- ✅ Find performance bottlenecks before production
- ✅ Ensure adequate test coverage for new code
- ✅ Verify documentation is complete and accurate
- ✅ Provide clear, actionable feedback with examples
- ✅ Complete in under 40 minutes for typical PRs
- ✅ Reduce production bugs by catching issues early

## Notes

- **Cost vs. Quality**: Four agent reviews cost more upfront but prevent expensive production issues
- **False Positives**: Agents may flag issues that aren't real—use judgment
- **Context Matters**: Some optimizations aren't worth it for low-traffic code
- **Learning Opportunity**: Review reports teach developers best practices

## See Also

- **Agentic Pattern**: https://github.com/nibzard/awesome-agentic-patterns/tree/main/patterns/feedback-loops
- **Related Workflow**: `/workflows:quality-feedback-loops`
- **Crackerjack Integration**: `/Users/les/Projects/crackerjack/`
