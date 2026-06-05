# ComfyUI Workflow Guidance

Whenever building or editing ComfyUI workflow JSON files, set the output filename prefix on the `Save Image` node or equivalent output node using this pattern:

```text
<diffusion-model>_<YYYY-MM-DD>_<sequence>
```

- `<diffusion-model>` is the diffusion model used by the workflow.
- `<YYYY-MM-DD>` is the current date. In ComfyUI filename fields, prefer `%date:yyyy-MM-dd%` so the workflow stays current each day.
- `<sequence>` is a three-digit sequence number for that date and diffusion model, starting at `001`.

Example:

```text
sdxl_base_2026-06-03_001
```

When possible, keep this filename rule portable and avoid hardcoded absolute paths.
