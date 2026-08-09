# draftwright API reference

draftwright turns a build123d solid or STEP file into an annotated manufacturing drawing.
This site documents the supported authoring and result surfaces; the repository's ADRs,
plans, and research notes are intentionally not part of the published navigation.

Start with one of three entry points:

- `make_drawing(...)` for a one-call export.
- `build_drawing(...)` when you want a `Drawing` to inspect, edit, lint, or export.
- `Sheet(...)` when you want to declare features and manufacturing intent explicitly.

The [README](https://github.com/pzfreo/draftwright#readme) is the getting-started guide.
Use this site when you need complete signatures, fluent-handle methods, and result methods.

## Reference sections

- [Entry points](reference/entry-points.md)
- [Sheet and fluent handles](reference/sheet.md)
- [Drawing results](reference/drawing.md)
- [Feature declarations](reference/declarations.md)
