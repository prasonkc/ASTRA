"""ASTRA voice wrapper backend package.

A speech frontend for the standalone ASTRA core: record from the microphone,
transcribe locally with **whisper.cpp**, ask the agent, and speak the reply with
**piper**. Everything is optional and local — nothing is sent off the machine.

See ``voice/ARCHITECTURE.md`` for the design and ``voice/README.md`` for setup.
"""
