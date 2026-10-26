# SD-114 Day Trader sandbox security review

## Scope and verdict

This is an independent review of the SideDeck wrapper around the pinned MIT source at commit
`3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`. The review covers Python-level network blocking,
environment and filesystem handling, subprocess controls, output limits and broker separation.

**Verdict: RESEARCH_ONLY acceptable for the pinned, reviewed source; untrusted skill execution is
NO-GO.** The wrapper is a containment boundary for this known source, not a general sandbox for
arbitrary Python. No OS-enforced isolation is available in the current Windows checkout.

## Findings

| Area | Control | Residual risk / disposition |
|---|---|---|
| Network | Child bootstrap patches `socket.connect`, `connect_ex`, `create_connection`, DNS resolution; environment strips credentials; upstream data commands require offline inputs. | Python monkey-patching is bypassable by native extensions, `ctypes`, or an interpreter/runtime escape. **NO-GO for untrusted code.** |
| Subprocess | Bootstrap patches `subprocess.Popen.__init__`; skill scripts run with `python -I`; the wrapper has a bounded timeout and output size. | A native call or alternate process API could escape Python-level hooks. **NO-GO for untrusted code.** |
| Filesystem | Inputs are copied into a fresh temporary workspace; path arguments reject absolute and parent traversal; outputs are snapshotted and bounded. | The process can still read any path permitted to its Windows identity if malicious code knows it. No ACL/job-object/AppContainer boundary is installed. **NO-GO for untrusted code.** |
| Credentials | Child environment is rebuilt from five harmless runtime variables; broker/provider names are not forwarded. | Parent process still has credentials, and source is executable Python. Never run an unreviewed or modified source. |
| Broker | `trader-broker` allows only ticket display; connector payload is replaced with `REFUSED_NOT_FORWARDED`; SideDeck order routes remain disabled. | No execution path is exposed by the module. |
| Provenance | Manifest pins version, commit, license and SHA-256 for all 11 scripts; reports retain source and data basis. | Genuine-data acceptance remains blocked until a separately approved licensed package exists. |

## Required future hardening before any untrusted skill

Run the worker in a separately provisioned OS boundary: a disposable Windows sandbox/AppContainer
or isolated VM/container with a read-only source mount, a dedicated low-privilege identity, no
network interface, no inherited handles, resource quotas, and an allowlisted output directory.
The Python wrapper alone must never be upgraded to an untrusted-execution authorization.
