# Usage

```{toctree}
:maxdepth: 1

examples/basic

```

## Generating MyST API docs

Once a project has been parsed into the SQLite IR, the generator renders it
into MyST Markdown that Sphinx indexes through its C++ domain:

```python
from clangquill.generator import Generator
from clangquill.store import Store

with Store.open("api.sqlite") as store:
    Generator(store).generate("docs/api")
```

This writes one page per top-level symbol plus an `index.md` toctree. Each
symbol becomes a real C++ domain object (`{cpp:class}`, `{cpp:function}`, …)
and inter-symbol links resolve through `{cpp:any}` roles.

Templates are the customization point. The Jinja environment looks up
`{kind}.md.jinja` (e.g. `class.md.jinja`, `function.md.jinja`) in your own
template directories *before* the bundled defaults, so dropping a file of the
same name overrides just that kind:

```python
Generator(store, template_dirs=["my_templates"]).generate("docs/api")
```


## Example notebooks statistics

```{nb-exec-table}
```
