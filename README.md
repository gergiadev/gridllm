# gridllm

> Experimental. I built gridllm to test an idea: a few LLM agents with strict roles, debating through a shared tool layer, might do better code analysis than one big assistant doing everything (with human support). **It is not production code.** The default config only knows one provider, the roles are prescriptive on purpose, and there are rough edges. Treat what it produces as a draft to review, not as something to trust blindly.

A grid of LLM agents for analysing C and Assembly code, with symbol tools for C, Assembly, Python and PHP source. You can use **uv** to install it once and run it from any directory. The agents work on the current directory.

Four roles, one shared MCP server:

| role | access | job |
|---|---|---|
| `worker` | **rw** | applies the changes that were decided |
| `thinker-1`, `thinker-2` | **r** | debate as proposer and opponent, roles swapping each exchange |
| `judge` | **r** | always turns the whole debate into the final verdict |

Permissions are enforced, not conventional. The MCP server hides write tools from read-only agents and refuses to run them anyway.

## Features

Two thinkers debate as proposer and opponent, a judge decides, and a worker executes. Read-only agents cannot see write tools at all. Every agent uses the same set of tools, scoped by role, and there are tools to list, find and extract symbol bodies for C, Assembly, Python and PHP.

The debate runs in exchanges. In each exchange one thinker is the **proposer** and every other thinker is an **opponent** whose job is to refute the proposal, not to replace it, and the roles swap at the next exchange. Proposals and objections are separate structures, not free text: an opponent files objections with the evidence it read, gridllm gives each one an id, and the next proposer has to close them by id. The debate ends only when the objection ledger is empty, every opponent accepts, the proposer reports `concluded` above `confidence_threshold`, and at least `min_exchanges` exchanges have run (a proposal nobody ever contested cannot close the debate). Otherwise it runs to `max_exchanges`. Either way the judge receives the transcript, the objections still open and the deduplicated findings, and produces the instruction the worker carries out.

The verdict names the files the worker is allowed to write, and the MCP server refuses every other path for the duration of the execution. The worker reports which files it changed, gridllm compares that with what was actually written, and the judge re-reads the result and approves or rejects it. Every exchange is saved to `./.gridllm/runs/`, so a failure late in the run does not throw the debate away; a single agent that fails takes down its own turn, not the run.

There is an optional TUI built with Textual, with live panels for debate, tools, verdict, execution, findings and logs. When rtk is on the PATH it is preferred for file reading. `max_input_tokens` is checked before every call, and older turns get summarised instead of letting the job fail. Each agent can use a different LiteLLM provider and API key.

## Architecture

```
                    +----------------------+
    CLI / TUI ----->|  orchestrator (Grid) | 
                    +-----------+----------+
                                |
                   +------------+------------+
                   v            v            v
               LLMClient     LLMClient     LLMClient
                (worker)    (thinker-N)     (judge)
                   |            |            |
                   +------------+------------+
                                |
                         +------v-------+
                         |   MCP server |  (streamable-http)
                         +------+-------+
                                |
                    tools: list_files, read_file, write_file,
                           edit_file, search_content, stat, shell,
                           git_diff, git_log, git_blame,
                           list_symbols, find_symbol, get_symbol_body
```

One exchange of the debate, with two thinkers:

```
  exchange 0    thinker-1 [proposer]  ---> proposal
                thinker-2 [opponent]  ---> objections [0-thinker-2-0, ...]
  exchange 1    thinker-2 [proposer]  ---> proposal + resolves [0-thinker-2-0]
                thinker-1 [opponent]  ---> objections           --> ledger empty?
  ...           up to max_exchanges

  always        judge   <- transcript + open objections + findings
                worker  <- verdict, restricted to allowed_files
                judge   <- review of what was actually written
```

The MCP server runs in-process on `127.0.0.1:12300/mcp` (configurable), and each agent connects to the same URL. The `?agent=` query parameter tells the `PermissionFilter` middleware which role is calling. Read-only agents get a filtered `tools/list` and are refused on `tools/call` for write tools. During execution the same middleware also holds the verdict's write scope: the worker keeps its `rw` access but every path outside `allowed_files` is refused until the execution ends.

### Symbol tools

`list_symbols`, `find_symbol` and `get_symbol_body` are powered by language parsers:

| language | parser | used for |
|---|---|---|
| C (`.c`, `.h`) | `tree-sitter` + `tree-sitter-c` | functions, prototypes, structs, unions, enums and their constants, typedefs, macros, globals, doc comments |
| Assembly (`.s`, `.asm`, `.S`) | stdlib `re` | macros, constants (`.equ`/`.set`), labels, directives, instructions |
| Python | stdlib `ast` | functions, classes, async defs, module-level variables, docstrings |
| PHP | `tree-sitter` + `tree-sitter-php` | functions, methods, classes, interfaces, traits, properties, consts, `use` declarations, globals |

C and PHP parsing need `tree-sitter` with the matching grammar, all in the default dependencies. Python and Assembly parsing use only the standard library.

`tree-sitter` is pinned below `0.26`: version `0.26.0` segfaults when reading node positions with the C grammar.

## Installation

Requires Python 3.13+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv tool install .
```

This puts `gridllm` in `~/.local/bin` inside an isolated environment. For development:

```bash
uv tool install --editable .
```

### Optional: TUI extra

The TUI uses [Textual](https://github.com/Textualize/textual) and is an optional dependency:

```bash
uv tool install . --with gridllm[gui]
```

Without the `[gui]` extra the `--tui` flag prints an explicit error, while the plain CLI keeps working.

## Setup

### 1. Clone

```bash
git clone git@github.com:gergiadev/gridllm.git
cd gridllm
```

### 2. rtk (optional, recommended)

To save some tokens, **rtk** has been introduced: if [rtk](https://github.com/rtk-ai/rtk) is installed and on the `PATH`, `gridllm` uses it for `read_file` instead of native Python reading, and routes the noisy inspection commands an agent runs through `shell` (`ls`, `tree`, `find`, `grep`, `rg`, `wc`, `git`) through the matching rtk subcommand. On a real workspace that turns a 1926-byte `ls -la` into 550 bytes and a 3494-byte `find` into 555. Detection is automatic at startup, so no configuration is needed.

The rewrite only ever touches the first word of a shell segment, and leaves alone anything quoted, any segment with a redirection, and commands whose output would be read back by another tool.

To install rtk:

```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
```

Verify it is visible:

```bash
which rtk && rtk --version
```

If rtk is not found, `gridllm` silently falls back to its native Python reader and runs shell commands unmodified. You do not need rtk to run the grid, but it is preferred when present.

### 3. rg and grep (search tools)

The `search_content` tool uses the fastest available searcher, detected at startup in this order:

1. [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) if on the `PATH`
2. `grep`/`egrep` as fallback
3. native Python search (walks files with `re`)

No configuration needed. To install ripgrep:

```bash
# Debian/Ubuntu
sudo apt install ripgrep

# macOS
brew install ripgrep

# cargo
cargo install ripgrep
```

Verify it is visible:

```bash
which rg && rg --version
```

If neither `rg` nor `grep` is found, `gridllm` falls back to a pure-Python search that walks the workspace with `re`. It works, but it is slower on large codebases.

### 4. C, Python and PHP parser dependencies

These are already in the default `pyproject.toml` dependencies, so a normal install covers them. They are listed here for transparency and for anyone building a custom environment.

| package | purpose |
|---|---|
| `tree-sitter>=0.24,<0.26` | tree-sitter runtime used by the C and PHP parsers |
| `tree-sitter-c>=0.24` | C grammar for tree-sitter |
| `tree-sitter-php>=0.23` | PHP grammar for tree-sitter |

Verify the parsers load:

```bash
python -c "import tree_sitter, tree_sitter_c, tree_sitter_php; print('parsers ok')"
```

The Python and Assembly parsers use only the standard library, so there is nothing extra to install for those.

### 5. API keys

API keys do not live in the configuration. Each agent declares which environment variable to use (`api_key_env`), so different agents can use different providers. The variables go in `~/.config/gridllm/.env`:

```
DEEPSEEK_API_KEY=sk-...
```

A missing variable blocks startup with an explicit message, instead of failing on the first billable call.

### 6. First-run bootstrap

On first run the default configuration is created and the command stops:

```bash
gridllm "analyse main.c"
# created the initial configuration at ~/.config/gridllm/config.yml
```

Write your API keys in `~/.config/gridllm/.env` (see above) and run again.

## Configuration

| path | contents |
|---|---|
| `~/.config/gridllm/config.yml` | agents, models, token limits, debug levels |
| `~/.config/gridllm/.env` | API keys |
| `./.gridllm/logs/grid.log` | per-project log for all agents |
| `./.gridllm/logs/tui.stdout.log` | stdio redirect when the TUI is running |
| `./.gridllm/runs/<timestamp>.json` | debate transcript and objection ledger, saved after every exchange |

Configuration and API keys live under XDG (`~/.config/gridllm/`). `XDG_CONFIG_HOME` and `GRIDLLM_CONFIG` are honoured (the latter points to an alternative config file, handy for keeping one per project).

Logs are local: `gridllm` creates `./.gridllm/logs/` in the directory you run it from, and the folder is in `.gitignore`.

The default `config.yml` ships with one `worker` (rw) on `openai/kimi-k2.7-code`, two `thinker` (r) on `openai/minimax-m3` and `openai/qwen3.5:397b` at `temperature: 0.6` and `0.3`, one `judge` (r) on `deepseek/deepseek-v4-pro`, and an MCP server at `127.0.0.1:12300/mcp`. The three Ollama Cloud agents go through its OpenAI-compatible endpoint at `https://ollama.com/v1`.

Keep `max_input_tokens` at or below the model's real context window and `max_output_tokens` at or below its output cap. gridllm uses `max_input_tokens` to decide when to summarise older turns and to refuse a call before sending it, so overstating it turns a clean compaction into a provider error mid-run.

Override models, providers, temperatures, token limits and debug levels per agent in `config.yml`. Each agent's `api_base` is optional and only needed for non-default endpoints.

A top-level `debate` section tunes how the thinkers interact. It is optional: leave it out and the defaults below apply.

```yaml
debate:
  max_exchanges: 5          # hard cap on proposer/opponent exchanges
  min_exchanges: 2          # exchanges that must run before consensus can be declared
  confidence_threshold: 0.8 # proposer confidence below which there is no consensus
  verify_execution: true    # the judge re-reads the changed files and rules on the result
```

Raise `confidence_threshold` to make the thinkers argue longer before the judge steps in, or lower it to cut the debate short. `min_exchanges: 1` allows an uncontested proposal to close the debate immediately, which is cheaper and considerably more gullible. Adding a third `thinker` to the grid works without further changes: one proposes and the other two refute in parallel.

An optional top-level `summarizer` names the agent that summarises older turns when the context fills up. Leave it out and each agent summarises its own conversation with its own model, or set it to an agent name to route every compaction through that one.

```yaml
summarizer: judge
```

## Usage

```bash
cd ~/projects/my-firmware
gridllm "find the out-of-bounds accesses in parser.c"
```

> **Warning:** the `worker` has write access to the directory you launch the command from. The agents are confined there (paths that escape it are rejected) but inside that fence they can modify files.

### With the TUI

```bash
gridllm --tui "find the out-of-bounds accesses in parser.c"
```

Without `--tui` the behaviour is the classic CLI (plain stdout, pipeable).

## TUI

Interactive terminal UI, styled after opencode, built with [Textual](https://github.com/Textualize/textual). It is a live, read-only view of what the grid is doing.

### Panels

| panel | content | default |
|---|---|---|
| DEBATE | thinker turns with stance, exchange, status, confidence, note | on |
| TOOLS | MCP calls and results in real time | on |
| VERDICT | judge adjudication and verdict | off |
| EXEC | worker output | on |
| FINDINGS | `file:lines` with summary for each finding | off |
| LOG | low-level LLM/tool log | off |
| TOKENS | per-agent token usage (prompt/completion/total) with budget bar | off |
| SIDEBAR | one-shot `list_files` snapshot of the workspace | off |

### Keymap

| key | action |
|---|---|
| CTRL+T | toggle TOOLS |
| CTRL+D | toggle DEBATE |
| CTRL+V | toggle VERDICT |
| CTRL+E | toggle EXEC |
| CTRL+F | toggle FINDINGS |
| CTRL+L | toggle LOG |
| CTRL+N | toggle TOKENS |
| CTRL+B | toggle SIDEBAR |
| CTRL+R | refresh SIDEBAR |
| F1 / CTRL+H | help |
| CTRL+Q / q | quit |

The TUI is read-only. The only user input is the initial task (passed on the CLI) and the toggle bindings.

## Debug

Each agent has an independent level in `config.yml`, and they all write to the same file:

| level | what shows up |
|---|---|
| `0` | nothing: the agent's activity is invisible |
| `1` | function names and who calls them |
| `2` | + the prompts sent to the model |
| `3` | + the model's reasoning, if it exposes it |

## Token limits

`max_output_tokens` caps generation, while `max_input_tokens` is the context window and is checked before every call. When the limit gets close, the oldest part of the conversation is summarised by the worker's model instead of letting the job fail.

## Tool rounds

`max_tool_rounds` (default `25`, per agent) bounds how many times an agent may call tools before it has to answer. In the last three rounds the tools are withheld and the agent is told to reply with the JSON object only; if the budget runs out anyway, one final call without tools is made before the run is failed. Raise it for models that explore a lot, or lower it to cut cost on agents that should answer quickly.

## Uninstall

Remove the tool and its isolated environment:

```bash
uv tool uninstall gridllm
```

Remove user configuration and logs (optional, do it only if you do not plan to reinstall):

```bash
rm -rf ~/.config/gridllm
rm -rf ~/.local/state/gridllm
```

If you cloned the repo for development and want to remove it too:

```bash
cd ..
rm -rf gridllm
```

## License

MIT License. See [LICENSE](LICENSE) for the full text.

```
MIT License

Copyright (c) 2026 Gerunda Gianluca

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
