# Instrument reference tables

`gen_reference.py` writes the option tables on the wiki's instrument reference
pages (`docs/wiki/Widget-Reference.md` and the `Widgets-*.md` pages) from
pyEFIS's instrument registry, `REGISTRY` in
`src/pyefis/screens/screenbuilder_factory.py`. That registry is what the
configurator builds its palette and Properties panel from, so the tables match
the code by construction.

Each generated block sits between `<!-- generated:<type> -->` and
`<!-- /generated -->` in a page; everything outside the markers is written by
hand. After a change to the registry, refresh the pages from the repository
root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python3 docs/images/reference/gen_reference.py --update docs/wiki
```

It prints the pages it changed, and any registered type that no page carries.
A second run changes nothing. To look first, `gen_reference.py OUTDIR` writes
each block to `OUTDIR/<type>.md` instead.

The script drops internal tracking references (issue and plan numbers) from
the help text, and links each type to its page under Flying it where there is
one. It needs PyQt6, because importing the registry imports the instruments.
