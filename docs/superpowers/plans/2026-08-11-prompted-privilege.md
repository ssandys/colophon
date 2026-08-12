# Prompted Privilege Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Amendment, 2026-08-12:** Task 5's on-machine verification found this plan's central retention premise false. polkit scopes an `auth_admin_keep` grant to `unix-process:PID:STARTTIME`, reusable only while that exact process lives; `systemctl` is always its own short-lived subject and exits within the same second, so no grant from one call ever survives to the next, and no logind session is resolvable as a fallback either (Omarchy runs the compositor under `user@1000.service`, not inside a `session-N.scope`). **Every start, stop, and restart prompts — there is no "one fingerprint per login" and no "second action is silent."** See `AGENTS.md` trap #31 for the full mechanism. This is accepted and documented, not a defect to fix. The plan as originally written (the Goal below, the Spec pointer, Task 1's ported code comment, Task 4's README replacement text, and Task 5's steps 3–4) told the retention story; those passages were corrected on 2026-08-12 to match trap #31. Task 5 was still open when this was found — follow its corrected steps below, not the original ones.

**Goal:** Delete Colophon's polkit rule and installer, and let Omarchy's own authentication dialog authorize `systemctl` instead — a prompt on every start, stop, and restart, not one fingerprint per login (see the 2026-08-12 amendment above).

**Architecture:** One line does the work. `colophon_action.py` stops sending `--no-ask-password`, which flips `allow_interactive_authorization` to true on the D-Bus call; `polkitd` then invokes the shell's registered agent. Everything else in this plan is deleting what the flag existed to support, inverting the guards that pinned it, and correcting a design record built on a false premise.

**Tech Stack:** Python 3 stdlib, ES5-subset JavaScript, QML, systemd/polkit.

**Spec:** `docs/superpowers/specs/2026-08-11-prompted-privilege-design.md`. Read it first — it carries the evidence for every claim below, including the `pkcheck` transcript. **Note the 2026-08-12 amendment above:** the transcript's subject was the invoking shell, not `systemctl`, so it says nothing about whether a second verb prompts — it does, every time. See `AGENTS.md` trap #31.

## Global Constraints

- **Python is stdlib-only, no pip ever.** Permitted: `datetime`, `glob`, `http.client`, `json`, `os`, `re`, `shlex`, `shutil`, `subprocess`, `sys`, `time`, `urllib.error`, `urllib.request`.
- **`Model.js` is ES5-subset and dual-engine.** No arrow functions, spread, template literals, `let`/`const`, `Object.assign`, `.includes(`, `.endsWith(`. Top level is `var`/`function` only. `ModelJsSyntaxTest` enforces it. Test files are exempt.
- **Never write a literal Unicode Private Use Area character** anywhere — code, docs, or commit message. Reference codepoints numerically (`chr(0xEE86)`) if you must manipulate one. A repo-wide scan is currently clean; keep it so.
- **`transient`, `volatile`, `synchronized`, `native`, `throws`, `goto`, `implements`** are reserved in QML's JS grammar. `qmllint` here reports every parse error as a bare exit 255 with **no message**.
- The unit name is the fixed literal `ollama.service`.
- Never edit `/usr/share/omarchy/`.
- **Standing safety rule:** no test may start, stop, or restart `ollama.service`, and none may pull or delete a model. Every privileged verb is asserted through `--dry-run` only. Task 5's by-hand checks are the deliberate exception.
- Baseline before you start: **119 Python + 24 JavaScript tests, 0 skips.**

## File Structure

| File | Change |
|---|---|
| `scripts/colophon_action.py` | Drop the flag; raise `SYSTEMCTL_TIMEOUT_SEC` 30 → 120 |
| `tests/test_action.py` | Invert three assertions that pin the flag |
| `tests/test_cross_language.py` | Invert one; drop the polkit-rule half of another |
| `Model.js` | `actionErrorText` stops naming a deleted script |
| `tests/model.test.js` | Update the refusal-phrasing test |
| `polkit/49-colophon-ollama.rules` | **Delete** |
| `bin/install-privileges` | **Delete** |
| `bin/test` | Drop its conditional lint of the deleted script |
| `README.md` | Delete the grant section, `--check`, `--remove`, and two Troubleshooting/Uninstall references |
| `AGENTS.md` | Correct traps 17 and 28; add a new trap for the premise failure |
| `docs/superpowers/specs/2026-08-10-colophon-design.md` | Dated corrections to the agent row and the privilege sections |

---

## Task 1: Stop suppressing the prompt

**Files:**
- Modify: `scripts/colophon_action.py:39` and its `systemctl_command`
- Test: `tests/test_action.py:20-40`, `tests/test_action.py:98-110`

**Interfaces:**
- Consumes: nothing.
- Produces: `systemctl_command(verb) -> list[str]` returning `["/usr/bin/systemctl", verb, "ollama.service"]` — three elements, no flag. `plan()`'s lifecycle output string becomes `"/usr/bin/systemctl <verb> ollama.service"`. Task 2's cross-language guard asserts the same absence.

- [ ] **Step 1: Invert the guard that pins the flag**

In `tests/test_action.py`, replace `test_no_ask_password_is_always_present` (line 30) entirely:

```python
    def test_the_prompt_is_never_suppressed(self):
        # --no-ask-password sets allow_interactive_authorization=false on the
        # D-Bus call, which turns Omarchy's authentication dialog into a bare
        # "Access denied". Re-adding it does not fail loudly -- every action
        # silently becomes permission denied, with no error anywhere. The flag
        # looks defensive, and galley is one copy-paste away, so this asserts
        # its absence rather than trusting nobody re-adds it.
        for verb in ("start", "stop", "restart"):
            with self.subTest(verb=verb):
                self.assertNotIn(
                    "--no-ask-password", action.systemctl_command(verb),
                    "the prompt must not be suppressed -- see "
                    "docs/superpowers/specs/2026-08-11-prompted-privilege-design.md")
```

- [ ] **Step 2: Update the two expected command strings**

`tests/test_action.py:27`, inside `test_lifecycle_verbs_are_one_systemctl_call`:

```python
                    ["/usr/bin/systemctl " + verb + " ollama.service"])
```

`tests/test_action.py:105`, inside `test_start_prints_the_command_and_exits_zero`:

```python
            "/usr/bin/systemctl start ollama.service")
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `python3 -m unittest tests.test_action -v`
Expected: FAIL — three failures, because the implementation still emits the flag. `test_the_prompt_is_never_suppressed` should report `--no-ask-password` unexpectedly found.

- [ ] **Step 4: Drop the flag and raise the timeout**

In `scripts/colophon_action.py`, replace `systemctl_command` entirely:

```python
def systemctl_command(verb):
    # No --no-ask-password. That flag sets allow_interactive_authorization to
    # false on the D-Bus call, so polkitd answers without ever consulting an
    # agent -- which is what turns Omarchy's authentication dialog into a bare
    # "Access denied". Omitting it lets polkitd raise the dialog and
    # pam_fprintd take a fingerprint -- but every call still prompts:
    # systemctl is its own short-lived polkit subject and exits within the
    # same second, so there is no auth_admin_keep grant left alive to reuse.
    # See AGENTS.md trap #31. No tty is involved at any point; polkit
    # authentication has never gone through one.
    return [SYSTEMCTL, verb, UNIT_NAME]
```

**Corrected 2026-08-12:** the code block above is what the comment should say, and what the shipped code says (see `AGENTS.md` trap #31). The plan originally specified a version claiming `auth_admin_keep` "covers the action for the rest of the session" — that clause was the same false retention premise this amendment corrects, and it is not what to implement if you are following this plan fresh.

And line 39:

```python
# The dialog's patience budget, not a command timeout: the call blocks while
# Omarchy's authentication prompt is open. 30s was chosen when a prompt was
# impossible, and is short for walking back to the desk -- the process would be
# killed mid-authentication and the panel would report a timeout for something
# the user was about to approve.
SYSTEMCTL_TIMEOUT_SEC = 120
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `python3 -m unittest tests.test_action -v`
Expected: PASS, 31 tests.

- [ ] **Step 6: Confirm the dry run shows the new command**

Run: `python3 scripts/colophon_action.py start --dry-run`
Expected, exactly: `/usr/bin/systemctl start ollama.service`

Do **not** run it without `--dry-run`. That would raise a dialog on the owner's screen; Task 5 covers the live check deliberately.

- [ ] **Step 7: Commit**

```bash
git add scripts/colophon_action.py tests/test_action.py
git commit -m "fix: let polkit prompt instead of suppressing the dialog"
```

---

## Task 2: Delete the rule and the installer

**Files:**
- Delete: `polkit/49-colophon-ollama.rules`, `bin/install-privileges`
- Modify: `bin/test`, `tests/test_cross_language.py:258-272`

**Interfaces:**
- Consumes: Task 1's flagless `systemctl_command`.
- Produces: a repo with no root-installed artifact and no `polkit/` directory. `UnitNameTest` keeps `test_the_unit_name_agrees_across_python_and_the_collector` and gains `test_the_prompt_is_never_suppressed_in_the_action_script`.

- [ ] **Step 1: Rewrite the two guards that reference deleted files**

In `tests/test_cross_language.py`, replace the whole `UnitNameTest` class (line 258 through the end of `test_systemctl_is_always_non_interactive`):

```python
class UnitNameTest(unittest.TestCase):
    def test_the_unit_name_agrees_across_python_and_the_collector(self):
        # Rename it in one place and every action fails with an error that
        # reads like a permissions problem rather than a typo.
        self.assertEqual(collect.UNIT_NAME, "ollama.service")
        action = read("scripts", "colophon_action.py")
        self.assertIn('UNIT_NAME = "ollama.service"', action)

    def test_the_prompt_is_never_suppressed_in_the_action_script(self):
        # The sibling assertion in tests/test_action.py checks the constructed
        # argv; this one checks the file, so a flag added anywhere -- a second
        # call site, a helper, a stray copy from galley -- is caught too.
        # Re-adding it converts every authentication dialog into a silent
        # "Access denied".
        #
        # Comments are stripped first, exactly as ModelJsSyntaxTest.code_only
        # does for Model.js: systemctl_command's own comment names the flag in
        # order to explain why it is absent, and prose *about* a banned
        # construct must not trip the guard. The strip is deliberately naive --
        # it would also cut a "#" inside a string literal, of which this file
        # has none.
        source = re.sub(r"#[^\n]*", "", read("scripts", "colophon_action.py"))
        self.assertNotIn("--no-ask-password", source)
```

Note the first method is renamed: it no longer reads the polkit rule, so its old name would lie.

- [ ] **Step 2: Run it and watch the second one fail**

Run: `python3 -m unittest tests.test_cross_language -v`
Expected: `test_the_unit_name_agrees_across_python_and_the_collector` passes; `test_the_prompt_is_never_suppressed_in_the_action_script` **passes too**, because Task 1 already removed the flag. If either fails, Task 1 is incomplete — stop and report rather than editing around it.

- [ ] **Step 3: Delete the rule, the installer, and the empty directory**

```bash
git rm polkit/49-colophon-ollama.rules bin/install-privileges
rmdir polkit 2>/dev/null || true
```

- [ ] **Step 4: Drop `bin/test`'s lint of the deleted script**

`bin/test` contains a conditional syntax check. Remove exactly these two lines:

```bash
if [ -f bin/install-privileges ]; then bash -n bin/install-privileges; fi
```

It is a single line, `bin/test:14`. Leave the `bash -n bin/install bin/dev-watch bin/test` line above it intact.

- [ ] **Step 5: Run the full suite**

Run: `./bin/test`
Expected: 119 Python + 24 JavaScript, 0 skips, exit 0. The count is unchanged: Task 1 renamed a test rather than adding one, and this task replaced two with two.

- [ ] **Step 6: Confirm nothing still references the deleted files**

Run: `grep -rn "install-privileges\|49-colophon" --include="*.py" --include="*.js" --include="*.qml" --include="*.sh" . | grep -v docs/superpowers`
Expected: exactly two hits, both of them Task 3's deliverable and neither yours
to fix — `Model.js`'s `actionErrorText` string and the `tests/model.test.js`
assertion that pins it. Anything else is a straggler and belongs to this task.
Hits in `README.md` and `AGENTS.md` are Task 4's job; hits under
`docs/superpowers/` are historical records and stay.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete the polkit rule and its installer"
```

---

## Task 3: Stop naming a script that no longer exists

**Files:**
- Modify: `Model.js` (`actionErrorText`)
- Test: `tests/model.test.js`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `actionErrorText(stderr)` returning `"not authorized — the authentication prompt was dismissed or denied"` for polkit's three refusal phrasings; unchanged otherwise (empty passthrough, 160-char truncation).

- [ ] **Step 1: Update the test first**

In `tests/model.test.js`, replace the `actionErrorText recognises every polkit refusal phrasing` test:

```javascript
test("actionErrorText explains a refused prompt without naming a script", () => {
  for (const phrase of ["Interactive authentication required",
                        "Access denied", "not authorized"]) {
    const text = Model.actionErrorText("systemctl: " + phrase + ".")
    assert.match(text, /not authorized/, phrase)
    // The old message told the user to run bin/install-privileges. That script
    // no longer exists, and a dismissed dialog was never a setup problem.
    assert.ok(!text.includes("install-privileges"), phrase)
    assert.ok(!text.includes("polkit rule"), phrase)
  }
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `node --test tests/model.test.js`
Expected: FAIL — the current implementation returns text containing `install-privileges`.

- [ ] **Step 3: Update the mapping**

In `Model.js`, replace the branch body inside `actionErrorText`:

```javascript
  if (text.indexOf("Interactive authentication required") >= 0 ||
      text.indexOf("Access denied") >= 0 ||
      text.indexOf("not authorized") >= 0) {
    return "not authorized — the authentication prompt was dismissed or denied"
  }
```

Leave the rest of the function untouched: the whitespace collapse, the empty-string passthrough, and the 160-character truncation all still apply to every other message.

- [ ] **Step 4: Run the JS suite**

Run: `node --test tests/model.test.js`
Expected: PASS, 24 tests.

- [ ] **Step 5: Confirm the ES5 subset still holds**

Run: `python3 -m unittest tests.test_cross_language.ModelJsSyntaxTest -v`
Expected: PASS. The em dash in the new string is ordinary Unicode, not a banned construct, but run the guard rather than assuming.

- [ ] **Step 6: Commit**

```bash
git add Model.js tests/model.test.js
git commit -m "fix: a dismissed prompt is not a missing setup step"
```

---

## Task 4: Correct the record

**Files:**
- Modify: `README.md`, `AGENTS.md`, `docs/superpowers/specs/2026-08-10-colophon-design.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: no code interface. This is the task that stops the repo describing a mechanism it no longer has.

- [ ] **Step 1: Strip the README's grant machinery**

Delete, in `README.md`:

- The `**Grant it privilege.**` paragraph at line 69 and everything through the `sudo bin/install-privileges --remove` block near line 115 — the whole grant, `--check`, and `--remove` sequence.
- The Troubleshooting sentences at lines 208–209 telling the reader to run the installer and confirm with `--check`.
- The Uninstall paragraph at lines 285–292 about removing the polkit rule first.

Replace the grant paragraph with a short statement of the new model:

```markdown
**Authentication.** Start, stop, and restart act on a *system* unit, so
**every** one of them raises Omarchy's authentication dialog — fingerprint if
you have one enrolled, password otherwise. Expect one prompt per click, not
one per login. Nothing to install, and Colophon can't touch the service
without you approving each action.
```

**Corrected 2026-08-12:** the paragraph above is what shipped, and it is correct. The plan originally specified text claiming authorization was "retained for the session, so a start and a later stop don't ask twice" — that was the same false retention premise this amendment corrects (see `AGENTS.md` trap #31), and it is not what to write if you are following this plan fresh.

Then re-read the surrounding text: the Install section previously flowed into the grant step, and the Uninstall section previously opened with "Remove the polkit rule *first*." Both need their connective sentences repaired, not just the blocks removed.

- [ ] **Step 2: Correct the two spec sections**

In `docs/superpowers/specs/2026-08-10-colophon-design.md`, replace the polkit-agent row at line 40:

```markdown
| polkit **agent** | **`omarchy.polkit`, a `service`-kind shell plugin with `keepLoaded: true`, running inside the shell process** | Corrected 2026-08-11 — this row previously read "none running", which was false when written. The check was `ps -eo args \| grep -i polkit`, which finds standalone agent *binaries*; an agent embedded in the shell process cannot appear in it. That false row is what ruled out `pkexec`, motivated the polkit rule, and deferred the boot toggle. See `2026-08-11-prompted-privilege-design.md` |
```

Then replace the bodies of `### The privilege grant` (line 316) and `### \`--check\` cannot use \`pkcheck\`` (line 355) with a pointer:

```markdown
### The privilege grant — superseded 2026-08-11

Both this section and the `--check` design below described a scoped polkit
rule and its installer, which have since been deleted. `systemctl` now prompts
through Omarchy's own agent. See
`2026-08-11-prompted-privilege-design.md`. The reasoning preserved here is
still accurate about polkit itself — `manage-units` gates every per-unit
operation, and `pkcheck` cannot pass details as an unprivileged caller — and
would apply again to anyone writing a rule.
```

Leave the `**Why the boot toggle is not in the MVP.**` passage at line 385 in place but add one sentence at its end noting the blocker is gone and the toggle is now a follow-up.

- [ ] **Step 3: Correct the traps and add the new one**

In `AGENTS.md`:

- **Trap 16** (pkcheck refuses details unprivileged) — leave the trap itself; it is still true. Change only its Guard column, which currently points at `bin/install-privileges --check`, to note that the script is gone and the fact stands for anyone querying polkit.
- **Trap 17** (`manage-units` gates every per-unit operation) — keep the fact; change its framing from "this is why our rule is verb-scoped" to "this is what to know if you ever write a rule."
- **Trap 28** (enable/disable cannot be scoped) — keep the fact; note the boot toggle is unblocked because prompting needs no rule at all.
- **Add trap 30**, immediately after trap 29:

```markdown
| 30 | An agent registered by another process is invisible to a process-list search. Colophon's original design recorded "no polkit agent is running", verified with `ps -eo args \| grep -i polkit`, and built a root-installed polkit rule on that premise. It was false the whole time: Omarchy's agent is a QML `service` plugin inside the shell process, and the journal had been logging `omarchy polkit agent registered` on every start. A first-party plugin (`tailscale/Service.qml`) was already calling `pkexec` from a QML `Process` — the exact thing the spec called impossible. | No guard test — this is a research failure, not a code defect. The lesson generalises: when checking whether a *service* exists, ask the bus (`busctl`, `pkcheck`) or read the consumer's own source, rather than grepping for a process that may be embedded in another. |
```

- [ ] **Step 4: Verify no stale references survive**

```bash
grep -rn "install-privileges\|49-colophon-ollama" README.md AGENTS.md
```

Expected: no output. `docs/superpowers/` retains historical mentions by design.

Then confirm the repo-wide PUA scan is still clean:

```bash
python3 -c "
import os
bad=[]
for r,d,fs in os.walk('.'):
    d[:]=[x for x in d if x not in ('.git','__pycache__','.superpowers')]
    for f in fs:
        if f.endswith('.png'): continue
        p=os.path.join(r,f)
        try: t=open(p,encoding='utf-8').read()
        except Exception: continue
        n=sum(1 for c in t if 0xE000<=ord(c)<=0xF8FF or ord(c)>=0xF0000)
        if n: bad.append((p,n))
print(bad or 'clean')"
```

- [ ] **Step 5: Run everything**

Run: `./bin/test`
Expected: 119 Python + 24 JavaScript, 0 skips, exit 0.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md docs/
git commit -m "docs: correct the record after deleting the polkit rule"
```

---

## Task 5: Verify on the machine

**Files:** none — this task changes nothing.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: the only evidence that any of this works. Nothing in this repository can raise a dialog or read a fingerprint.

**This task is for the owner, not an agent.** It starts and stops the real service and requires someone watching the screen. An implementer must not run it.

Preconditions, both already true and worth re-confirming: no rule at `/etc/polkit-1/rules.d/49-colophon-ollama.rules`, and `ollama.service` inactive.

- [x] **Step 1: Deploy**

```bash
cd ~/Src/colophon && ./bin/install && omarchy restart shell
```

- [x] **Step 2: First action raises the dialog**

Open the panel, click **start**. Expect Omarchy's themed authentication dialog, offering fingerprint. Authenticate; the service should start and the panel should move through `starting…` to `running`.

- [x] **Step 3: The second action prompts again (corrected 2026-08-12)**

Click **stop**. Expect Omarchy's authentication dialog to appear **again**.
`systemctl` is its own short-lived polkit subject and exits within the same
second it's authorized, so nothing from the start in step 2 survives to
cover this call — see `AGENTS.md` trap #31. **A second prompt is the
correct, passing result here, not a failure.** Authenticate; the service
should stop as expected, and there should be no `Ollama stopped`
notification, since you asked for the stop yourself. That second half also
re-checks the `expectedStop` race that took three fix rounds.

(This step originally read "The second action is silent" and expected **no**
dialog, on the premise that the session's authorization from step 2 covered
it. That premise is false — see the amendment at the top of this plan — so
if you see no dialog here, that is the failure, not the pass.)

- [x] **Step 4: A dismissed dialog reads sensibly**

Click **start**, then dismiss the dialog without authenticating. Expect the panel's error strip to say the action was not authorized, with no mention of a script or a missing rule, and the button to become clickable again rather than staying disabled.

- [x] **Step 5: Report what happened**

Record the outcome of each step in the spec's "Testing" section, marking each verified or not. Do not mark anything verified that was not observed on screen.

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Drop `--no-ask-password` | 1 |
| `SYSTEMCTL_TIMEOUT_SEC` 30 → 120 | 1 |
| Delete the rule, the installer, the README grant section | 2, 4 |
| Invert the four flag assertions | 1 (three), 2 (one) |
| Drop the polkit-rule half of the unit-name guard | 2 |
| `actionErrorText` stops naming the script | 3 |
| Dated corrections: agent row, privilege sections | 4 |
| Traps 16, 17, 28 reframed; new premise-failure trap | 4 |
| Boot toggle out of scope | not implemented; noted in trap 28 and the spec pointer |
| Migration instructions omitted | deliberately absent; no install base |
| Three by-hand verifications | 5 |

**Note on test counts.** Every task states 119 Python + 24 JavaScript because no task adds or removes a test — Task 1 renames one, Task 2 replaces two with two, Task 3 rewrites one. If a count moves, something was added that the plan did not ask for; investigate rather than updating the expectation.
