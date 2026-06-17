"""Entry point wired as a UserPromptSubmit hook. Reads the event JSON on stdin,
emits an optional context-injection JSON on stdout. Always exits 0."""
import json
import sys

from .run import run


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    out = run(event)
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
