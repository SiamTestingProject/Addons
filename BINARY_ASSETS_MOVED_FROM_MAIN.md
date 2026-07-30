# Binary assets moved from deployment package

The main deployment ZIP is intended for platforms such as Hugging Face Spaces, where direct Git pushes may reject binary files unless Xet storage is configured.

The following binary files were moved from the main deployment package into:

`Addons/project_root_overlay/`

- `resources/extras/inline.jpg`
- `resources/extras/template.jpg`
- `resources/extras/ultroid.jpg`
- `resources/extras/ultroid_assistant.jpg`
- `resources/extras/ultroid_blank.png`
- `resources/startup/__pycache__/hf_health.cpython-313.pyc`

To restore these assets into a full runtime tree, copy the contents of `Addons/project_root_overlay/` over the project root.
