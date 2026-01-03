#!/usr/bin/env python3
"""
Test harness for nlsh - allows automated interaction testing via PTY.

Usage:
    # Simple test - check if remote mode shows correct message
    python test_nlsh.py --remote --send "write a simple script that echoes hello" \
                        --expect "Executing script on remote"

    # Interactive conversation test
    python test_nlsh.py --remote --conversation '
        expect: $
        send: write a shell script that echoes hello and run it
        expect: Execute?
        send: y
        expect: on remote
    '
"""

import os
import pty
import select
import signal
import sys
import time
import argparse
import re
from dataclasses import dataclass
from typing import Optional


# ANSI escape code pattern for stripping colors
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE.sub('', text)


@dataclass
class TestStep:
    """A single step in a test conversation."""
    action: str  # "send", "expect", "wait", "expect_not"
    value: str
    timeout: float = 30.0


class NLShellTester:
    """Test harness for nlsh using PTY for realistic terminal interaction."""

    def __init__(
        self,
        remote: bool = False,
        danger_mode: bool = False,
        llm_off: bool = False,
        verbose: bool = False,
    ):
        self.remote = remote
        self.danger_mode = danger_mode
        self.llm_off = llm_off
        self.verbose = verbose
        self.master_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.output_buffer = ""
        self.all_output = ""  # Complete log of all output

    def log(self, msg: str):
        """Print verbose log message."""
        if self.verbose:
            print(f"[TEST] {msg}", file=sys.stderr)

    def start(self) -> str:
        """Start nlsh and return initial output up to first prompt."""
        script_dir = os.path.dirname(os.path.abspath(__file__))

        self.pid, self.master_fd = pty.fork()

        if self.pid == 0:
            # Child process - execute nlsh
            os.chdir(script_dir)

            # Build command
            python = os.path.join(script_dir, '.venv/bin/python3')
            args = [python, 'nlshell.py']
            if self.remote:
                args.append('--remote')
            if self.danger_mode:
                args.append('--dangerously-skip-permissions')

            self.log(f"Executing: {' '.join(args)}")
            os.execv(python, args)
            # Never returns

        # Parent process - wait for startup banner and first prompt
        self.log(f"Started nlsh with PID {self.pid}")

        try:
            # Wait for the prompt (ends with $)
            output = self._read_until('$ ', timeout=30)
            return output
        except TimeoutError:
            # Return what we have
            return self.output_buffer

    def _read_available(self) -> str:
        """Read all currently available data without blocking."""
        data = ""
        while True:
            r, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not r:
                break
            try:
                chunk = os.read(self.master_fd, 4096)
                if not chunk:
                    break
                decoded = chunk.decode('utf-8', errors='replace')
                data += decoded
                self.all_output += decoded
            except OSError:
                break
        return data

    def _read_until(self, pattern: str, timeout: float = 30.0) -> str:
        """Read output until pattern is found or timeout."""
        start = time.time()

        while time.time() - start < timeout:
            self.output_buffer += self._read_available()

            # Check for pattern (strip ANSI for matching)
            clean_buffer = strip_ansi(self.output_buffer)
            if pattern in clean_buffer:
                result = self.output_buffer
                # Move buffer past the pattern
                idx = clean_buffer.find(pattern) + len(pattern)
                # Find corresponding position in original buffer
                self.output_buffer = self.output_buffer[idx:] if idx < len(self.output_buffer) else ""
                self.log(f"Found pattern '{pattern}'")
                return result

            time.sleep(0.05)

        raise TimeoutError(
            f"Pattern '{pattern}' not found after {timeout}s.\n"
            f"Buffer contents:\n{strip_ansi(self.output_buffer)[-500:]}"
        )

    def send(self, text: str) -> None:
        """Send text to nlsh (adds newline)."""
        self.log(f"Sending: {text}")
        os.write(self.master_fd, (text + '\n').encode())
        time.sleep(0.1)  # Brief pause to let it process

    def send_raw(self, text: str) -> None:
        """Send text without adding newline."""
        self.log(f"Sending raw: {repr(text)}")
        os.write(self.master_fd, text.encode())
        time.sleep(0.1)

    def expect(self, pattern: str, timeout: float = 30.0) -> str:
        """Wait for pattern in output and return matched output."""
        return self._read_until(pattern, timeout)

    def expect_not(self, pattern: str, timeout: float = 2.0) -> bool:
        """Verify pattern does NOT appear within timeout. Returns True if not found."""
        try:
            self._read_until(pattern, timeout)
            return False  # Found - bad
        except TimeoutError:
            return True  # Not found - good

    def get_output(self) -> str:
        """Get any pending output."""
        self.output_buffer += self._read_available()
        return strip_ansi(self.output_buffer)

    def get_all_output(self) -> str:
        """Get complete output log."""
        return strip_ansi(self.all_output)

    def run_conversation(self, steps: list[TestStep]) -> tuple[bool, str, list[str]]:
        """
        Run a conversation script.

        Returns:
            (success, final_output, error_messages)
        """
        errors = []

        for i, step in enumerate(steps):
            step_desc = f"Step {i+1}: {step.action} '{step.value[:50]}...'" if len(step.value) > 50 else f"Step {i+1}: {step.action} '{step.value}'"
            self.log(step_desc)

            try:
                if step.action == "send":
                    self.send(step.value)

                elif step.action == "send_raw":
                    self.send_raw(step.value)

                elif step.action == "expect":
                    self.expect(step.value, step.timeout)

                elif step.action == "expect_not":
                    if not self.expect_not(step.value, step.timeout):
                        errors.append(f"{step_desc}: Pattern WAS found (should not be)")

                elif step.action == "wait":
                    time.sleep(float(step.value))

                else:
                    errors.append(f"{step_desc}: Unknown action '{step.action}'")

            except TimeoutError as e:
                errors.append(f"{step_desc}: {e}")
                break
            except Exception as e:
                errors.append(f"{step_desc}: {type(e).__name__}: {e}")
                break

        return len(errors) == 0, self.get_all_output(), errors

    def close(self):
        """Clean up resources."""
        if self.master_fd is not None:
            try:
                # Send exit command
                os.write(self.master_fd, b'exit\n')
                time.sleep(0.5)
            except:
                pass

            try:
                os.close(self.master_fd)
            except:
                pass
            self.master_fd = None

        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
                time.sleep(0.3)
            except:
                pass
            try:
                os.kill(self.pid, signal.SIGKILL)
            except:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except:
                pass
            self.pid = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def parse_conversation(text: str) -> list[TestStep]:
    """
    Parse a conversation script.

    Format:
        expect: pattern
        send: text to send
        wait: seconds
        expect_not: pattern that should not appear
    """
    steps = []

    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        if ':' not in line:
            continue

        action, value = line.split(':', 1)
        action = action.strip().lower()
        value = value.strip()

        # Handle timeout suffix like "expect[60]: pattern"
        timeout = 30.0
        if '[' in action and ']' in action:
            action_base, timeout_str = action.split('[')
            timeout = float(timeout_str.rstrip(']'))
            action = action_base

        steps.append(TestStep(action=action, value=value, timeout=timeout))

    return steps


def main():
    parser = argparse.ArgumentParser(
        description='Test nlsh interactively via PTY',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test remote mode shows correct execution message
  python test_nlsh.py --remote --conversation '
      expect: $
      send: write a shell script that echoes hello and run it
      expect: Execute?
      send: y
      expect: on remote
  '

  # Quick check that nlsh starts
  python test_nlsh.py --expect-startup

  # Verbose mode to see all interactions
  python test_nlsh.py --remote -v --conversation '...'
        """
    )

    parser.add_argument('--remote', action='store_true',
                        help='Start nlsh in remote mode')
    parser.add_argument('--danger', action='store_true',
                        help='Start with --dangerously-skip-permissions')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed test progress')
    parser.add_argument('--timeout', type=float, default=60,
                        help='Overall test timeout (default: 60s)')

    # Test specification options
    parser.add_argument('--expect-startup', action='store_true',
                        help='Just verify nlsh starts successfully')
    parser.add_argument('--conversation', type=str,
                        help='Multi-line conversation script')
    parser.add_argument('--send', action='append', default=[],
                        help='Send a command (can repeat)')
    parser.add_argument('--expect', action='append', default=[],
                        help='Expect a pattern (can repeat)')

    args = parser.parse_args()

    # Set up alarm for overall timeout
    def timeout_handler(signum, frame):
        print(f"\n[TIMEOUT] Test exceeded {args.timeout}s limit", file=sys.stderr)
        sys.exit(2)

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(args.timeout))

    # Run the test
    with NLShellTester(
        remote=args.remote,
        danger_mode=args.danger,
        verbose=args.verbose
    ) as tester:

        print(f"Starting nlsh (remote={args.remote})...")
        startup_output = tester.start()

        if args.verbose:
            print(f"\n--- Startup Output ---\n{strip_ansi(startup_output)}\n--- End Startup ---\n")

        # Check startup succeeded
        if 'Error' in startup_output and 'nlsh' not in startup_output.lower():
            print(f"FAILED: nlsh failed to start")
            print(strip_ansi(startup_output))
            sys.exit(1)

        if args.expect_startup:
            print("PASSED: nlsh started successfully")
            sys.exit(0)

        # Build conversation steps
        steps = []

        if args.conversation:
            steps = parse_conversation(args.conversation)
        else:
            # Build from --send and --expect args
            for cmd in args.send:
                steps.append(TestStep("send", cmd))
            for pattern in args.expect:
                steps.append(TestStep("expect", pattern))

        if not steps:
            print("No test steps specified. Use --conversation, --send, or --expect")
            print("\nCurrent output buffer:")
            print(tester.get_output()[:1000])
            sys.exit(0)

        # Run the conversation
        success, output, errors = tester.run_conversation(steps)

        if success:
            print("PASSED: All test steps completed successfully")
            if args.verbose:
                print(f"\n--- Full Output ---\n{output[-2000:]}\n--- End Output ---")
            sys.exit(0)
        else:
            print("FAILED: Test errors:")
            for err in errors:
                print(f"  - {err}")
            print(f"\n--- Output (last 2000 chars) ---\n{output[-2000:]}\n--- End Output ---")
            sys.exit(1)


if __name__ == '__main__':
    main()
