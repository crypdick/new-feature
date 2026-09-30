## Test-driven development

For behavior changes and bug fixes, use test-driven development with these steps:

1. **Red:** Add or update a focused failing test that proves the required behavior or reproduces the bug. Run the targeted test and confirm it fails for the expected reason.
2. **Green:** Implement the smallest change that makes the test pass. Run the targeted test again and confirm it passes.
3. **Refactor:** Clean up the implementation while keeping the targeted test green, then run the relevant broader test set.

Don't skip the red step unless there is no practical test boundary. If you skip it, state why and run the closest meaningful verification instead.
