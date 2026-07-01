# Generic UCloud Tooling Audit

## Verdict

This repository is a good foundation, but it is **not yet a generic UCloud job platform**.

What it already does well:

- submits and monitors UCloud jobs
- writes SSH config automatically
- uploads scripts, packages, and inputs over SSH
- downloads outputs back to the local machine
- terminates jobs after completion
- analyzes utilization reports
- packages delivery bundles

What is still missing is the **platform layer** that turns these primitives into reusable, standard job types.

## What is already reusable

The current code base already gives you:

- a working UCloud API client for jobs and wallet browsing
- template-based job submission
- generic Python job execution
- a proof-of-concept SSH transfer flow that stays available as a test
- utilization report parsing and recommendation generation
- delivery bundle creation
- script scaffolding for extraction jobs

That means the repo is past the “raw API client” stage, but it is still early in the “generic workflow platform” stage.

## What is missing

### 1. Job profile registry

The repo currently has command-line flags and a few hardcoded demo flows, but it does **not** have a formal registry of reusable job types.

What is missing:

- a declarative job profile schema
- a registry of standard profiles
- a maintained catalog of reusable `UCLOUD_TEMPLATE_JOB_ID` values by job family
- profile-specific defaults for mounts, commands, outputs, and analysis
- profile-specific validation rules
- profile-specific post-run handling

Without this, every new workflow becomes a one-off CLI composition instead of a standard tool.

### 2. Machine catalog and selection logic

The repo can submit a job with a size string, but it does not know what machine types actually exist or what they are good for.

What is missing:

- an overview of all available UCloud machine types
- a capability model for CPU, memory, and GPU resources
- a way to compare machine types by workload fit
- automatic “size up / size down” suggestions
- a selector that maps job requirements to machine classes
- a catalog that maps job families to known-good template jobs

This is critical if you want the tool to help the user efficiently rather than just submit a job blindly.

### 3. Storage and data staging model

Current behavior is file-by-file upload/download plus optional mounts.

What is missing:

- a first-class input staging layer
- a first-class output staging layer
- separate concepts for:
  - working directory
  - scratch directory
  - reference data
  - writable outputs
  - delivery outputs
- mount aliases or mount naming
- checksum / completeness verification for transferred data
- real-world validation of UCloud mount behavior against a live job

This matters for anything beyond a small Python script.

The mount path handling in the current code should be treated as **unverified until a live UCloud job has confirmed it works end to end**.

### 4. Environment bootstrapping

At the moment, setup is just a list of shell commands.

What is missing:

- a reusable dependency model for Python packages
- support for multiple install strategies:
  - `pip install`
  - editable local package installs
  - requirements files
  - lockfile-based installs
  - future container/image-based bootstraps
- explicit preflight checks before execution
- explicit post-run cleanup hooks

This is the infrastructure needed for anything like GPU inference, large dependency trees, or reproducible batch jobs.

### 5. Artifact and provenance model

The repo can download named outputs and an optional utilization report, but it does not yet define a full run artifact contract.

What is missing:

- a standard manifest for each run
- a canonical layout for:
  - inputs
  - outputs
  - logs
  - utilization reports
  - scripts
  - environment metadata
- checksum tracking
- versioned provenance metadata
- job-to-delivery traceability

Without this, the platform cannot reliably package or audit results across job types.

### 6. Observability and failure handling

The current workflows terminate jobs and print progress, but they do not yet behave like a real orchestration layer.

What is missing:

- structured job state tracking
- stderr/stdout capture as first-class artifacts
- remote exit-code capture
- timeout policy by job type
- retry policy by job type
- failure classification:
  - user error
  - dependency failure
  - resource exhaustion
  - UCloud infrastructure failure

This is especially important for memory-bound jobs and GPU jobs.

### 7. Utilization feedback loop

There is now utilization analysis, but it is still a standalone tool.

What is missing:

- per-profile utilization heuristics
- memory-crash detection rules
- GPU saturation rules
- automatic “rerun with another size” suggestions
- historical comparisons across runs
- profile-aware recommendations

This is the core feedback loop you need for optimizing machine size.

### 8. Workflow composition layer

The repo has single-run workflows, but not a composition system.

What is missing:

- a way to chain standard job types
- a way to reuse inputs from one step as outputs of another
- a pipeline definition format
- later, a DAG/orchestration layer

For now, this does not need to be a full workflow engine, but it does need to exist as a design concept.

### 9. UX and discoverability

Current CLI commands are useful, but they are still low-level.

What is missing:

- `ucloud machines` or equivalent machine overview
- `ucloud profiles` or equivalent standard job-type listing
- a “run profile” command that takes a named standard job type
- help text that reflects real use cases, not only technical primitives
- generated example configurations for each standard profile

### 10. Test and release structure

The repository has good unit coverage, but a generic platform needs more than unit tests.

What is missing:

- integration tests for profile definitions
- contract tests for machine selection
- smoke tests for standard job types
- fixture-based tests for utilization reports from CPU and GPU jobs
- regression tests for artifact manifests

## Recommended architecture

The generic tool should probably be organized into these layers:

1. **Profiles**  
   Declarative standard job types.

2. **Machines**  
   Discovery and ranking of machine types.

3. **Staging**  
   Input upload, mount handling, output download, report download.

4. **Execution**  
   Submit, wait, run, monitor, terminate.

5. **Reports**  
   Utilization parsing, recommendation logic, anomaly detection.

6. **Artifacts**  
   Provenance, manifests, delivery bundle creation.

7. **CLI / UX**  
   Human-facing commands that expose the profiles and machine catalog cleanly.

## What should exist in the code base next

The next missing primitives are:

- a machine catalog module
- a job profile registry module
- a shared job-run manifest schema
- a profile-aware runner that can execute any standard job type
- a profile-aware utilization analyzer
- a standardized output bundle format

## Practical conclusion

If you want this repo to become a generic UCloud tool, the next phase is **not more ad hoc command flags**.

It is:

- standard job definitions
- machine discovery
- profile-aware orchestration
- artifact/provenance tracking
- utilization-guided optimization
