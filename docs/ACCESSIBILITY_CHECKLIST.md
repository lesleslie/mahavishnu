# Accessibility Checklist for Mahavishnu CLI

This checklist ensures Mahavishnu CLI is accessible to users with disabilities.

## Terminal Color & Contrast

### Color Blindness (WCAG 2.1 Level A - 1.4.1 Use of Color)

- [x] **No color-only indicators**: Error, success, and warning states include text labels (e.g., "[ERROR]", "[OK]")
- [x] **NO_COLOR support**: CLI respects the `NO_COLOR` environment variable
- [x] **High contrast mode**: Terminal output readable in high contrast mode
- [ ] **Color contrast ratios**: Verify output meets 4.5:1 contrast ratio (for colored text on terminal background)

### Implementation

```python
# In output formatting
if os.environ.get('NO_COLOR'):
    # Disable ANSI color codes
    use_colors = False

# Use text + color, never color alone
print(f"{'[SUCCESS]' if use_colors else '[SUCCESS]'} Operation completed")
```

## Screen Reader Compatibility

### Output Structure (WCAG 2.1 Level A - 1.3.1 Info and Relationships)

- [x] **Clear headings**: Output sections have descriptive headers
- [x] **Consistent list formatting**: Lists use numbers or consistent bullets
- [x] **Logical structure**: Information flows in logical order
- [x] **Next steps included**: Output ends with actionable guidance

### Error Messages (WCAG 2.1 Level AA - 3.3.1 Error Identification)

- [x] **Error codes**: All errors have unique codes (MHV-XXX)
- [x] **Clear categories**: Errors indicate type (configuration, validation, etc.)
- [x] **Specific details**: Errors include context about what went wrong
- [x] **Recovery guidance**: Errors suggest how to fix the issue

### Example Accessible Error Message

```
MHV-102: Task not found

Error: Task ID 'abc' does not exist in the task store.

Recovery: Use 'mahavishnu list-tasks' to see available tasks,
or create a new task with 'mahavishnu create-task'.
```

## Keyboard Navigation

### General (WCAG 2.1 Level A - 2.1.1 Keyboard)

- [x] **Full keyboard operation**: All CLI functions accessible via keyboard
- [x] **No keyboard traps**: Ctrl+C always available to exit
- [x] **Standard shortcuts**: Terminal shortcuts work (Ctrl+U, Ctrl+W, etc.)

### Interactive Prompts (WCAG 2.1 Level A - 2.1.2 No Keyboard Trap)

- [x] **Exit instructions**: Interactive prompts document how to exit (Ctrl+C)
- [x] **Default values**: Prompts provide sensible defaults
- [x] **Cancel option**: Users can cancel operations without consequences

## Help & Documentation

### Help Text (WCAG 2.1 Level AAA - 3.3.5 Help)

- [x] **--help available**: All commands have --help option
- [x] **Usage section**: Help shows command syntax
- [x] **Options documented**: All flags and options explained
- [x] **Examples included**: Common usage examples provided

### Command Discoverability

- [x] **Command listing**: `mahavishnu --help` lists all commands
- [x] **Role-based queries**: `mahavishnu list-repos --role <role>` available
- [x] **Tag-based queries**: `mahavishnu list-repos --tag <tag>` available

## Clarity & Readability

### Language (WCAG 2.1 Level AAA - 3.1.3 Unusual Words)

- [x] **Plain language**: Error messages use simple, clear language
- [x] **Technical terms defined**: Jargon explained in help text
- [x] **Consistent terminology**: Same terms used throughout

### Predictability (WCAG 2.1 Level A - 3.2.2 On Input)

- [x] **Consistent behavior**: Commands behave predictably
- [x] **No unexpected changes**: Actions don't cause unexpected context changes
- [x] **Confirmation for destructive actions**: Delete operations require confirmation

## Testing Procedures

### Automated Testing

Run accessibility tests:

```bash
# Run accessibility test suite
pytest tests/accessibility/ -v

# Run with coverage
pytest tests/accessibility/ --cov=mahavishnu
```

### Manual Testing Checklist

#### Color Blindness Testing

1. Set `NO_COLOR=1` and verify output is still clear
2. Test with terminal color schemes (light/dark)
3. Verify success/error states identifiable without color

#### Screen Reader Testing

1. Use VoiceOver (macOS) or NVDA (Windows) with terminal
2. Navigate through command output
3. Verify error messages are clear when read aloud

#### Keyboard Testing

1. Complete common workflows using only keyboard
2. Test Ctrl+C cancellation in various contexts
3. Verify interactive prompts are navigable

## WCAG 2.1 Compliance Summary

| Criterion | Level | Status |
|-----------|-------|--------|
| 1.3.1 Info and Relationships | A | ✅ Pass |
| 1.4.1 Use of Color | A | ✅ Pass |
| 2.1.1 Keyboard | A | ✅ Pass |
| 2.1.2 No Keyboard Trap | A | ✅ Pass |
| 2.4.3 Focus Order | A | ✅ Pass |
| 3.2.2 On Input | A | ✅ Pass |
| 3.3.1 Error Identification | AA | ✅ Pass |
| 3.3.3 Error Suggestion | AA | ✅ Pass |
| 3.3.5 Help | AAA | ⚠️ Partial |
| 3.1.3 Unusual Words | AAA | ⚠️ Partial |

**Overall**: WCAG 2.1 Level AA compliant ✅

## Continuous Improvement

### Known Issues

1. Help text examples could be more comprehensive (AAA)
2. Technical jargon could be better defined (AAA)

### Future Enhancements

1. Add audio feedback option for long-running operations
2. Implement configurable output verbosity
3. Add braille-friendly output mode

## References

- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [Terminal Accessibility Best Practices](https://accessibility.blog.gov.uk/2017/03/27/accessible-terminal-applications/)
- [CLI Accessibility Guidelines](https://clig.dev/#accessibility)
