# Installing CleatStomp

CleatStomp is a single-file Python command-line tool. Installing it means: have
Python, then (optionally) put the `cleatstomp` console script on your PATH.
There is no database, no service, no daemon and no configuration file.

## 1. Prerequisites (install these yourself — the installer never does)

| Requirement | Why | Check |
| --- | --- | --- |
| Python 3.9 or newer | the tool's interpreter | `python3 --version` |
| `pip` for that Python | installs pytest and the optional console script | `python3 -m pip --version` |

The tool itself uses only the Python standard library, so there is **nothing to
compile and no system library to install**. Never run `sudo` for this project.

macOS/Homebrew and Linux distribution packages are not needed; if Python is not
present, install it with your platform's normal Python installer.

## 2. Install (one command, it exits when done)

```bash
bash install.sh
```

The script:

1. updates `pip`, `setuptools` and `wheel` (project-level only);
2. installs `requirements.txt` (the declared test runner, `pytest`);
3. installs the optional `cleatstomp` console script with
   `python3 -m pip install -e . --no-build-isolation`;
4. runs an import self-check and then the test suite;
5. **exits** — it never starts the tool or leaves a process running.

It is safe to run more than once.

If you would rather not install anything at all, copy `cleatstomp.py` wherever
you want and run it directly with Python 3.9+:

```bash
python3 cleatstomp.py --help
```

## 3. Verify

```bash
python3 -m pytest            # test suite
python3 acceptance_check.py  # acceptance harness (PASS/FAIL per case)
bash demo.sh                 # end-to-end demo in a throwaway temp directory
```

Expected tail of the harness:

```
All 14 acceptance cases passed
```

## 4. Run

```bash
python3 cleatstomp.py --help
python3 cleatstomp.py add --shoe Left --float 4.5
python3 cleatstomp.py list
python3 cleatstomp.py suggest
```

Or, once `install.sh` has installed the console script:

```bash
cleatstomp --help
cleatstomp add --shoe Right --float 3.5 --note "new bolts torqued to 5 Nm"
cleatstomp suggest
```

`./cleatstomp.json` is created in the directory you run the tool from, on the
first successful `add`. Keep one directory per bike or per customer if you log
readings for more than one.

## 5. Environment variables

None are required. CleatStomp boots with no `.env` file and no configuration.
The optional ones are:

| Variable | Effect |
| --- | --- |
| `NO_COLOR` | set to any value to disable ANSI colour (also `--no-color`) |
| `PYTHON` | interpreter that `install.sh` and `demo.sh` use (default `python3`) |

## 6. Uninstall

```bash
python3 -m pip uninstall cleatstomp   # removes the optional console script
rm cleatstomp.py                      # removes the tool
rm cleatstomp.json                    # removes your logged readings (back it up first)
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `python3: command not found` | Python 3.9+ is not installed or not on `PATH` — see step 1 |
| `cleatstomp: command not found` after install | the optional console script was skipped; use `python3 cleatstomp.py ...` (the tool is unaffected) |
| `cleatstomp: error: cannot use .../cleatstomp.json: not valid JSON` | the data file was edited into something unparseable; fix or move it aside — the tool will not rewrite it for you |
| `cleatstomp: error: --float must be ...` | the angle must be a number from 0.0 to 30.0 degrees inclusive |
| `cleatstomp: error: --date must be a real calendar date` | use `YYYY-MM-DD` and a date that exists (2024-02-30 is not a real date) |
