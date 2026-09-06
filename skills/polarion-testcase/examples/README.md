# Examples

Sample steps files for use with `steps-file=` option.

| File | Description |
|---|---|
| `steps_basic.yaml` | Simple YAML steps (no setup/teardown) |
| `steps_with_setup_teardown.yaml` | YAML steps with setup and teardown sections |
| `steps_multi_setup_teardown.yaml` | Multiple setup and teardown steps (numbered list) |
| `steps_plain_text.txt` | Plain text format with numbered steps and section headers |

## Usage

Copy an example and modify it for your test:

```bash
cp examples/steps_with_setup_teardown.yaml /tmp/my_steps.yaml
# edit /tmp/my_steps.yaml
```

Then pass it to the skill:

```
/polarion-testcase create tests/functional/test_foo.py::test_bar steps-file=/tmp/my_steps.yaml
```
