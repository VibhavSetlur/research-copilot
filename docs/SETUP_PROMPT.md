Copy this into the first chat turn after opening the project folder in your AI
IDE. Edit the bracketed details, but keep the verification-first posture.

```text
I'm setting up this folder as a Research OS project, and I want you to guide the
setup rather than jumping into analysis.

Project context: [two or three sentences about the study/tool/program, the real
decision or deadline, and who will review the work]. Current files are [where the
data, notes, papers, old notebooks, or code live]. Some details may be missing or
wrong: [known uncertainty, prior failed attempt, incomplete de-identification,
HPC/privacy/IRB constraint, or collaborator concern].

Please do the setup in a verification-first order:
1. Check whether `research-os` is installed and whether this folder is already a
   workspace. If it is not, propose the exact `research-os init` command and ask
   before using `--force` or overwriting any existing Research OS files.
2. Infer the workspace mode only after reading my context; if more than one mode
   fits, ask one clarifying question instead of guessing.
3. Wire only the IDE I am using unless I ask for more. After wiring, remind me to
   restart/reload the IDE before expecting MCP tools.
4. Run `research-os doctor` or the equivalent health checks and summarize failures
   with fixes. Verify paths and environment before touching data.
5. If a daemon would help because of long jobs, shared HPC, hard gates, or
   notifications, explain why and ask before starting it. Do not imply it is a
   chat gateway or model proxy.
6. Onboard the project: scan `inputs/`, fill intake, profile data only after path
   verification, check literature/provenance, and identify stale or untrusted
   prior work.
7. Before analyzing real data, ask for approval of the plan and any data movement
   (copy vs symlink), especially for restricted or large files.

At the end, tell me: what was configured, what you verified, what is still
ambiguous, what files changed, and the safest next step.
```

## ▲ Copy to here

---

## Why each part matters

| Part | Why it is there |
|---|---|
| **Project context** | The AI needs the messy research reality: goal, audience, files, failures, constraints, and uncertainty. |
| **One editor, not all** | Setup should wire the IDE you are using, not scatter configs you do not need. |
| **The restart** | MCP servers load when a session starts, so tools usually appear only after reopening the project. |
| **The self-test** | Setup that is not verified is not setup. The AI should prove install, workspace health, and MCP routing before touching data. |
| **Onboard before analysis** | Jumping to "run the model" skips framing, literature grounding, and data provenance. |
| **Ask before real data work** | Copying large/restricted data, starting long jobs, or analyzing unverified files should require explicit confirmation. |
| **Optional daemon** | The daemon adds durable execution, gates, budgets, and notifications; it is not an LLM gateway. |

**Next:** [START.md](START.md) for the full guided walkthrough · [SCENARIOS.md](SCENARIOS.md)
to watch realistic projects run end to end · [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
for the concepts behind it.
