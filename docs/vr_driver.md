# VR Driver: output & deployment notes

This document describes how to run the simple VR driver output used by the project and how to deploy it.

Usage
- The application sends skeleton and tracker updates via OSC to the configured `osc_ip` and `osc_port`.
- Ensure `osc_port` in `config.json` is set to the target receiver (e.g., VRChat OSC bridge).

Deployment
- Build the release binary using:

```bash
cargo build --release
```

- Copy the generated binary from `target/release/aetherpose` to the target machine and run.

Notes
- For integration with external VR runtimes (e.g., VRChat), use the OSC endpoint expected by the runtime. Consider adding a small helper script to translate skeleton joint names if necessary.
