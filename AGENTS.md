# Project entrypoint

Before working in this repository, read **PROJECT_STATUS.md**. It is the single source of truth for development progress, deployment evidence, verification, and next steps.

## Preserve the user's decisions

- Upload existing audio files; no microphone capture, real-time transcription, or required mobile app.
- NAS coordinates jobs; prefer the Windows GPU over LAN, fall back to NAS CPU when unavailable.
- Preserve the original `/data` mount, existing records, and other services. The actual NAS web port is **18088**, container port **8787**.
- Clean temporary audio on completion, failure, and termination. Do not label work terminated before local cleanup completes.
- Use the 1.3 web import/test workflow for computer connections; do not send the user back to manual URL/token environment-variable setup.
- Never copy passwords, tokens, session secrets, or real transcript content into progress documentation or logs. Runtime secret locations are in PROJECT_STATUS.md.

## Deployment and validation

- A built package or successful ARM64 simulation does not prove the physical NAS is updated. Verify `/api/health` and actual job routing.
- The ECS deployment, physical NAS, local build, and native Windows worker can run different versions. Confirm the target before changing it.
- Read a test's setup and side effects before running it. Use isolated QA containers/volumes; do not substitute production containers for hardcoded QA names.
- Do not modify or reinstall the user's existing FunASR environment unnecessarily.

## Keep the handoff current

After meaningful work, update PROJECT_STATUS.md with the current state, verification performed, release identity, unresolved limitations, and the next concrete step. Keep README.md as an entrypoint rather than a second competing progress log.
