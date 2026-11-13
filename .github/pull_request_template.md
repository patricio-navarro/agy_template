## Summary
<!-- Describe the module, fix, or improvement to agy_template -->

## Checklist
- [ ] Module follows `CONTRIBUTING_MODULES.md` and requires no hardcoded changes to `scripts/agy_init.py` (or explains why engine support was needed)
- [ ] All `SKILL.md` files include valid `name` and third-person `description` YAML frontmatter
- [ ] `./agy-init --validate-catalog` passes with 0 errors
- [ ] `python3 -m unittest discover -s tests -v` passes 100%
- [ ] Committed Markdown files use portable relative links only (zero `file:///` links)
