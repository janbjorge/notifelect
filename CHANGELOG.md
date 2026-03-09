# Changelog

## Unreleased

### Breaking Changes

#### Module renames

| Before | After |
|---|---|
| `notifelect.election_manager` | `notifelect.election` |
| `notifelect.tm` | `notifelect.task_manager` |

#### Class renames

| Before | After |
|---|---|
| `Outcome` | `ElectionResult` |
| `Electoral` | `ElectionRound` |
| `MessageCreator` | `MessageFactory` |
| `QueryBuilder` | `SQLBuilder` |

#### Method and attribute renames

| Before | After |
|---|---|
| `Queries.query_builder` | `Queries.sql` |
| `Queries.sequence()` | `Queries.next_sequence()` |
| `QueryBuilder.sequence` | `SQLBuilder.sequence_name` |
| `QueryBuilder.create_install_query()` | `SQLBuilder.install_sql()` |
| `QueryBuilder.create_uninstall_query()` | `SQLBuilder.uninstall_sql()` |
| `QueryBuilder.create_next_sequence_query()` | `SQLBuilder.next_sequence_sql()` |
| `QueryBuilder.create_notify_query()` | `SQLBuilder.notify_sql()` |

### Bug Fixes

- Fix crash when no pong messages arrive during an election round (`max()` on empty list).
- Fix listener never being removed on exit (lambda vs method reference mismatch).
- Replace `assert` with proper runtime check in ping handler (assertions are stripped by `python -O`).

### Improvements

- Simplify timeout logic using `asyncio.wait_for` instead of manual task juggling.
- Use `tasks.discard` instead of `tasks.remove` in `TaskManager` to avoid `KeyError`.
- Tighten `Queries.notify` type hint from `BaseModel` to `MessageExchange`.
- Clean up docstrings: remove boilerplate, keep only useful information.
- Fix typos in CLI help text ("addinal" -> "additional") and test filename ("test_eletion" -> "test_election").
