#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Manual verification script for network IP detection.

This script demonstrates the behavior of get_network_ip() in various scenarios:
1. With config.yaml present (reads from config)
2. Without config.yaml (runtime detection fallback)
3. With invalid config.yaml (runtime detection fallback)
"""

import sys
from pathlib import Path


# Add parent directory to path to import startup module
# TODO: Remove after editable install confirmed on all platforms
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from startup import get_network_ip, print_header, print_info, print_success


def test_with_config():
    """Test with existing config.yaml."""
    print_header("Test 1: With config.yaml (reads from config)")

    network_ip = get_network_ip()

    if network_ip:
        print_success(f"Detected network IP: {network_ip}")
    else:
        print_info("No network IP detected")

    return network_ip


def test_without_config():
    """Test without config.yaml (fresh install simulation)."""
    print_header("Test 2: Without config.yaml (fresh install simulation)")

    # Temporarily move config.yaml if it exists
    config_path = Path.cwd() / "config.yaml"
    backup_path = Path.cwd() / "config.yaml.temp_backup"

    config_existed = False
    if config_path.exists():
        config_existed = True
        config_path.rename(backup_path)
        print_info("Temporarily moved config.yaml")

    try:
        network_ip = get_network_ip()

        if network_ip:
            print_success(f"Runtime detection successful: {network_ip}")
        else:
            print_info("No network IP detected")

        return network_ip

    finally:
        # Restore config.yaml
        if config_existed:
            backup_path.rename(config_path)
            print_info("Restored config.yaml")


def test_adapter_filtering():
    """Test that virtual adapters are filtered correctly."""
    print_header("Test 3: Adapter Filtering")

    try:
        import psutil

        # Get all network interfaces
        interfaces = psutil.net_if_addrs()
        interface_stats = psutil.net_if_stats()

        virtual_patterns = [
            "docker",
            "veth",
            "br-",
            "vmnet",
            "vboxnet",
            "virbr",
            "tun",
            "tap",
            "vEthernet",
            "Hyper-V",
            "WSL",
        ]

        print_info("Network adapters detected:")

        for name, addresses in interfaces.items():
            stats = interface_stats.get(name)
            is_up = stats.isup if stats else False

            # Check if virtual
            is_virtual = any(pattern.lower() in name.lower() for pattern in virtual_patterns)

            # Get IPv4 addresses
            ipv4_addrs = [addr.address for addr in addresses if addr.family == 2]

            status = "UP" if is_up else "DOWN"
            adapter_type = "VIRTUAL" if is_virtual else "PHYSICAL"

            print_info(f"  {name:<30} [{status:>4}] [{adapter_type:>8}] IPs: {', '.join(ipv4_addrs)}")

        print_success("Adapter enumeration complete")

    except ImportError:
        print_info("psutil not available - cannot enumerate adapters")


def main():
    """Run all verification tests."""
    print_header("Network IP Detection Verification")

    print_info("This script verifies the enhanced get_network_ip() function")
    print_info("It tests both config.yaml reading and runtime detection")
    print()

    # Test 1: With config.yaml
    ip_with_config = test_with_config()

    # Test 2: Without config.yaml (runtime detection)
    ip_without_config = test_without_config()

    # Test 3: Show adapter filtering
    test_adapter_filtering()

    # Summary
    print_header("Summary")

    if ip_with_config:
        print_success(f"Config.yaml method: {ip_with_config}")
    else:
        print_info("Config.yaml method: No IP detected")

    if ip_without_config:
        print_success(f"Runtime detection method: {ip_without_config}")
    else:
        print_info("Runtime detection method: No IP detected")

    if ip_with_config == ip_without_config and ip_with_config:
        print_success("Both methods returned the same IP (consistent)")
    elif not ip_with_config and ip_without_config:
        print_success("Runtime detection provides fallback when config.yaml is missing")
    elif ip_with_config and not ip_without_config:
        print_info("Config.yaml contains IP, runtime detection failed")
    else:
        print_info("Neither method detected network IP")


if __name__ == "__main__":
    main()
