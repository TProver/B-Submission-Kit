# Atelier B plug-in design notes

Last updated: 2026-04-23

Working notes for the D06-BSubmissionKit plug-in, grounded in the official extension manual ([Manual_Extensions_ng.md](Manual_Extensions_ng.md)), the `Plugin_Development_Manual.pdf` shipped with Atelier B, and the working examples we studied.

## 1. Install location (version-dependent)

| Atelier B build | Plug-in folder | Loaded at |
|---|---|---|
| CSSP 4.6.0-rc7 (legacy) | `<install>\extensions\` | GUI startup |
| Community Edition 24.04.2 | `<install>\share\plugins\` | GUI startup |
| Professional Edition 25.02 | `<install>\share\plugins\` | GUI startup |

The `AtelierB.exe` binary of CE 24.04.2 contains the hard-coded relative path `../share/plugins`. If the target folder does not exist, the installer must create it (requires admin rights on `C:\Program Files\...`).

The folder is scanned once at GUI startup; changes require a full restart.

## 2. `.etool` file format (minimum working)

Validated on CE 24.04.2 with [plugin/BSKHello.etool](../plugin/BSKHello.etool):

```xml
<externalTool name="BSKHello"
              category="project"
              label="BSK Hello"
              shortcut="Ctrl+Alt+H"
              tooltip="..."
              icon="bsk_hello.png">
    <command>"${extensionsDir}\bsk_hello.cmd"</command>
    <param>${projectName}</param>
    <param>${projectBdp}</param>
</externalTool>
```

**Mandatory attributes on `externalTool`**: `name`, `category`, `label`.
**Optional but recommended**: `shortcut`, `tooltip`, `icon` (a `.png` sibling of the `.etool`).

**`category` values observed:**
- `project`: menu entry appears in the **Project** menu. Greyed out until a project is opened; enabled when a project is active.
- `component`: menu entry appears in the **Component** menu. Tied to a selected component.

## 3. Features beyond the minimal example

Seen in Professional Edition 25.02 plug-ins (`validaterulesprj.etool`, `bxmlproject.etool`, `bxmlcomponent.etool`):

- **`menu="POG2"` attribute on `externalTool`**: groups several tools into a named sub-menu under Project / Component. Useful once we have many plug-ins.
- **`<translation locale="fr_FR"><label>...</label><tooltip>...</tooltip></translation>`**: localized label and tooltip per locale. We should ship English default + French translation (teaching is in French).
- **`<param fileExists="...">...</param>`**: conditional parameter, only passed to the command if the file exists. Pattern:
  ```xml
  <param fileExists="${projectBdp}/AtelierB">-r</param>
  <param fileExists="${projectBdp}/AtelierB">${projectBdp}/AtelierB</param>
  ```
  This is how the Pro 25.02 plug-ins pass the project-specific `AtelierB` resource file when it exists.
- **`<componentList />`**: inside a `project`-category tool, expands to the list of all components in the project. Lets a single invocation iterate the whole project (exactly what we need for per-submission verification).
- **`<toolParameter type="tool" default="oprgui">`**: auto-resolves a tool name against Atelier B's standard search path (`bbin/<os>`, `share/plugins/<name>`, `share/plugins/<name>/<os>`), so the plug-in doesn't hardcode full paths and stays cross-platform.

## 4. `toolParameter` types (from the manual)

| Type | Use |
|---|---|
| `ressource` | Text content is an Atelier B resource key (`ATB*BART*RefinerFile` style). Expanded to the resource value. |
| `exefile` | Path to an external executable. User-editable in Preferences. `default` supplies initial value. |
| `file` | Path to a configuration file. User-editable in Preferences. |
| `tool` | A tool shipped by Atelier B or our extension. Searched in `bbin/<os>`, `share/plugins/<tool>`, `share/plugins/<tool>/<os>`. |

## 5. Predefined variables (from the manual)

| Variable | Available in | Meaning |
|---|---|---|
| `${projectName}` | all | Current project name |
| `${projectBdp}` | all | Absolute path to project `bdp/` directory |
| `${extensionsDir}` | all | Absolute path to the plug-in directory (= `share/plugins/` in 24.04.2+) |
| `${componentName}` | component | Selected component name |
| `${componentPath}` | component | Absolute path to the selected component file |
| `${componentDir}` | component | Directory of the selected component |

Not in the vanilla manual but seen in CSSP `.etool` files: `${projectTrad}`, `${csspKernel}` (CSSP-specific, added by that variant's build). Do not rely on them in CE/Pro plug-ins.

## 6. Implications for D06-BSubmissionKit

Given the goal (student submits a model; plug-in pushes to a classroom server on the teacher's PC; server runs verification and shows a live dashboard), the `.etool` surface is:

- **One `project`-category plug-in**: "Submit to classroom". Collects `${projectName}`, `${projectBdp}`, expands `<componentList />` to bundle the components, pushes everything (archive + metadata) to the server.
- **A `<toolParameter type="file">` for the server URL** (so each student can configure the classroom server address once, from Preferences).
- **Optional second plug-in**: "Check classroom status", which opens the dashboard URL in a browser. `category="project"`.
- **The real work happens in whatever binary `<command>` launches** (Python script, Go / .NET client, etc.). The `.etool` only provides the menu entry and argv assembly.
- **Verification on the server side** uses `bbatch` and/or the Atelier B MCP server, outside the plug-in's concern.
- **Installer**: a small admin-run `.cmd` or `.ps1` that creates `share/plugins/` (if absent), copies the `.etool` + icon + client binary, and tells the user to restart Atelier B. Model it on [plugin/install_test.cmd](../plugin/install_test.cmd).

## 7. Open questions still pending verification

- Does `<componentList />` emit one `<param>`-like token per component, or pass the list as a single argument? Need to run a prototype.
- Is there a way to surface a dialog (e.g., "submission sent, server ack OK / timeout") without writing our own WinForms / Qt app? Candidate approaches: PowerShell `MessageBox`, a tiny Python/Tk one-shot, or a built-in Atelier B notification we don't know about yet.
- Atelier B opens the **Tasks** window for external-tool output; we should confirm the server client's stdout/stderr lands there when the plug-in fires.

## 8. What the hello-world test proved

Run on 2026-04-23 against CE 24.04.2 (project `Algo_CC_arc` open):

- Menu entry "BSK Hello" appears in Project menu with icon and `Ctrl+Alt+H` shortcut.
- Greyed out with no project, enabled when one is open (as expected for `category="project"`).
- Click + shortcut both fire the command.
- `${projectName}` → `Algo_CC_arc`, `${projectBdp}` → `C:\Work\B\WK25.02\Algo_CC_arc\bdp` (both substituted correctly).
- Command runs silently (no visible UI), just appends to `c:\tmp\bsk-hello.log`.
