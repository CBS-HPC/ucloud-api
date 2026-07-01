# Standard UCloud Job Types

This catalog defines the reusable job profiles that the platform should support.

The goal is not to hardcode one-off workflows. The goal is to define **named job types** with shared infrastructure, so the CLI can run them consistently.

## Shared profile fields

Each standard job type should eventually declare:

- `name`
- `description`
- `category`
- `required_machine_capabilities`
- `template_job_id`
- `input_contract`
- `output_contract`
- `mount_contract`
- `bootstrap_commands`
- `run_command`
- `report_paths`
- `analysis_strategy`
- `delivery_strategy`
- `cleanup_policy`

## Standard job types

### 1. `cpu-python-batch`

Purpose:

- run a Python script on a CPU machine
- upload inputs and optional local code
- download named output files

Infrastructure needed:

- Python script upload
- optional local package installation
- explicit input and output manifests
- optional utilization report download
- cleanup after completion

### 2. `python-package-batch`

Purpose:

- run a Python script with a local package or project tree
- install the package on the remote job before execution

Infrastructure needed:

- package upload
- editable install or wheel install support
- reproducible dependency bootstrap
- standard artifact layout for inputs and outputs

### 3. `data-staging-job`

Purpose:

- stage reference data into a job
- stage results out of a job

Infrastructure needed:

- mount abstraction
- staging aliases for input / output / scratch
- checksum verification
- transfer logs
- retry-aware copy handling

### 4. `report-analysis-job`

Purpose:

- analyze utilization or other machine-generated reports
- recommend whether to rerun with a different machine size

Infrastructure needed:

- report downloader
- parser registry
- recommendation engine
- human-readable report output
- optional Markdown artifact export

### 5. `gpu-batch-inference`

Purpose:

- run large-scale inference jobs on GPU machines
- batch prompts or records through a model

This is the profile family that would cover a `vLLM`-style batch inference setup.

Infrastructure needed:

- GPU machine catalog
- VRAM-aware machine selection
- model artifact staging
- cache warmup and reuse strategy
- batch input manifest
- structured output records
- GPU utilization analysis
- memory-pressure detection

### 6. `interactive-debug-session`

Purpose:

- open an SSH-accessible job for interactive debugging
- keep the job around while the user inspects files or logs

Infrastructure needed:

- persistent SSH alias
- optional VS Code remote support
- log access
- manual stop semantics

### 7. `delivery-packaging-job`

Purpose:

- package results, docs, and scripts into a standardized delivery bundle

Infrastructure needed:

- artifact manifest
- output directory layout
- provenance metadata
- bundle signing/checksums if needed later

### 8. `pipeline-step`

Purpose:

- provide a reusable unit for a multi-step workflow
- chain one standard job type into another later

Infrastructure needed:

- pipeline definitions
- dependency edges
- shared artifact naming
- resume/retry semantics

## How to use this catalog

These job types should become the basis for:

- CLI presets
- config files
- template job selection
- documentation examples
- machine-type recommendations
- future pipeline composition

## Practical rule

If a job type repeats, it belongs in this catalog.

If it only exists once, it should stay as an example or a temporary script.

