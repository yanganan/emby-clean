# Product Notes

## Core Workflow

1. Sync metadata from Emby into a local SQLite cache.
2. Select one or more libraries.
3. Run a scan mode.
4. Review grouped results on a dedicated results page.
5. The current page auto-selects only recommended delete candidates.
6. Confirm selected rows and append them to the delete queue.
7. The delete worker processes one item at a time and logs each step.

## AV Priority

For AV duplicate groups, the default keep priority is:

```text
破解-C > C > 破解 > 无标签
```

Items with `流出`, `泄露`, or `leak` are marked as manual-review candidates. They are not auto-selected by the recommended-delete button.

## Delete Queue Semantics

- Each delete request appends rows to `delete_queue`.
- A single background worker consumes pending rows.
- New rows can be appended while the worker is running.
- Each item is deleted through Emby first.
- The worker polls Emby until the item disappears.
- Only after confirmation does it remove the local cache row and move to the next item.

## Future Improvements

- Dry-run reports before deletion.
- Export selected groups to CSV.
- Rule tester for checking how two file names are grouped.
- Optional allowlist for libraries, paths, actors, or collections.
- Scan history dashboard with hit counts and failure counts.

