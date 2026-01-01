#!/usr/bin/env python3
"""Key generation utility for nlsh Ed25519 keypairs.

This script generates Ed25519 keypairs for the nlsh chain-of-trust security model:
- nlsh keypair: Used by nlsh client to sign messages to MCP server
- mcp keypair: Used by MCP server to sign messages to nlsh_remote

Usage:
    # Generate nlsh keypair
    python keygen.py nlsh

    # Generate MCP server keypair
    python keygen.py mcp

    # Generate both keypairs
    python keygen.py all

    # Custom output directory
    python keygen.py nlsh --output-dir /custom/path

Keys are saved to ~/.nlsh/keys/ by default:
    - nlsh_private.key / nlsh_public.key
    - mcp_private.key / mcp_public.key
"""

import argparse
import sys
from pathlib import Path

from asymmetric_crypto import (
    generate_keypair,
    save_private_key,
    save_public_key,
    get_public_key_hex,
)


DEFAULT_KEY_DIR = Path.home() / ".nlsh" / "keys"


def generate_nlsh_keypair(output_dir: Path) -> None:
    """Generate keypair for nlsh client."""
    private_key, public_key = generate_keypair()

    private_path = output_dir / "nlsh_private.key"
    public_path = output_dir / "nlsh_public.key"

    save_private_key(private_key, private_path)
    save_public_key(public_key, public_path)

    print(f"Generated nlsh keypair:")
    print(f"  Private key: {private_path}")
    print(f"  Public key:  {public_path}")
    print(f"  Public key (hex): {get_public_key_hex(private_key)}")


def generate_mcp_keypair(output_dir: Path) -> None:
    """Generate keypair for MCP server."""
    private_key, public_key = generate_keypair()

    private_path = output_dir / "mcp_private.key"
    public_path = output_dir / "mcp_public.key"

    save_private_key(private_key, private_path)
    save_public_key(public_key, public_path)

    print(f"Generated MCP server keypair:")
    print(f"  Private key: {private_path}")
    print(f"  Public key:  {public_path}")
    print(f"  Public key (hex): {get_public_key_hex(private_key)}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Ed25519 keypairs for nlsh chain-of-trust authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s nlsh              Generate nlsh client keypair
    %(prog)s mcp               Generate MCP server keypair
    %(prog)s all               Generate both keypairs
    %(prog)s nlsh -o /tmp      Custom output directory

Key Distribution:
    After generating keys, distribute public keys as follows:
    - nlsh_public.key -> MCP server (for verifying nlsh signatures)
    - mcp_public.key  -> nlsh_remote server (for verifying MCP signatures)

    Private keys should NEVER be shared:
    - nlsh_private.key stays on the nlsh client machine
    - mcp_private.key stays on the MCP server machine
"""
    )

    parser.add_argument(
        "type",
        choices=["nlsh", "mcp", "all"],
        help="Type of keypair to generate"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_KEY_DIR,
        help=f"Output directory for keys (default: {DEFAULT_KEY_DIR})"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Overwrite existing keys without prompting"
    )

    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing keys
    keys_to_check = []
    if args.type in ("nlsh", "all"):
        keys_to_check.extend([
            args.output_dir / "nlsh_private.key",
            args.output_dir / "nlsh_public.key",
        ])
    if args.type in ("mcp", "all"):
        keys_to_check.extend([
            args.output_dir / "mcp_private.key",
            args.output_dir / "mcp_public.key",
        ])

    existing_keys = [k for k in keys_to_check if k.exists()]
    if existing_keys and not args.force:
        print("Warning: The following keys already exist:")
        for k in existing_keys:
            print(f"  {k}")
        response = input("Overwrite? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(1)

    # Generate keys
    if args.type in ("nlsh", "all"):
        generate_nlsh_keypair(args.output_dir)

    if args.type in ("mcp", "all"):
        if args.type == "all":
            print()  # Blank line between outputs
        generate_mcp_keypair(args.output_dir)

    print()
    print("Key generation complete.")
    print()
    print("Next steps:")
    if args.type in ("nlsh", "all"):
        print(f"  1. Copy {args.output_dir / 'nlsh_public.key'} to the MCP server")
    if args.type in ("mcp", "all"):
        print(f"  2. Copy {args.output_dir / 'mcp_public.key'} to the nlsh_remote server")
    print()
    print("Configure environment variables:")
    if args.type in ("nlsh", "all"):
        print(f"  nlsh:       NLSH_PRIVATE_KEY_PATH={args.output_dir / 'nlsh_private.key'}")
    if args.type in ("mcp", "all"):
        print(f"  nlsh_mcp:   NLSH_MCP_PRIVATE_KEY_PATH={args.output_dir / 'mcp_private.key'}")
        print(f"              NLSH_PUBLIC_KEY_PATH={args.output_dir / 'nlsh_public.key'}")
    if args.type in ("mcp", "all"):
        print(f"  nlsh_remote: NLSH_MCP_PUBLIC_KEY_PATH={args.output_dir / 'mcp_public.key'}")


if __name__ == "__main__":
    main()
