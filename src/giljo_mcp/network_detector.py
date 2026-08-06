# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Dynamic Network Adapter IP Detection for Giljo HQ.

This module provides runtime IP detection for network adapters to support
CORS configuration updates when adapter IPs change.
"""

import logging

import psutil


logger = logging.getLogger(__name__)


class AdapterIPDetector:
    """Detect current IP address of network adapters for CORS configuration."""

    def __init__(self):
        self.virtual_patterns = [
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
        self.loopback_patterns = ["lo", "Loopback"]

    def get_adapter_ip(self, adapter_id: str) -> str | None:
        """Get current IP address of a specific network adapter."""
        try:
            interfaces = psutil.net_if_addrs()

            if adapter_id not in interfaces:
                logger.warning(f"Adapter {adapter_id!r} not found in system interfaces")
                return None

            addresses = interfaces[adapter_id]

            for addr in addresses:
                if addr.family == 2:  # AF_INET (IPv4)
                    ip = addr.address
                    if not ip.startswith("127."):
                        logger.debug(f"Adapter {adapter_id!r} has IP: {ip}")
                        return ip

            logger.warning(f"Adapter {adapter_id!r} has no IPv4 address")
            return None

        except (OSError, KeyError, AttributeError) as e:
            logger.error(f"Failed to get IP for adapter {adapter_id!r}: {e}", exc_info=True)
            return None

    def detect_ip_change(self, config: dict) -> tuple[bool, str | None, str | None]:
        """Detect if network adapter IP has changed from initial/stored configuration.

        If no adapter is configured but mode is 'auto', will auto-detect best adapter.
        """
        try:
            security = config.get("security", {})
            network = security.get("network", {})
            mode = network.get("mode", "localhost")

            adapter_id = network.get("selected_adapter")
            initial_ip = network.get("initial_ip")

            # Auto-detect adapter if not specified and mode is 'auto'
            if not adapter_id and mode == "auto":
                recommended = self.get_recommended_adapter()
                if recommended:
                    adapter_id, current_ip = recommended
                    logger.info(f"Auto-detected adapter: {adapter_id!r} with IP {current_ip}")
                    # First run - no initial IP to compare
                    if not initial_ip:
                        return False, current_ip, adapter_id
                    # Compare with stored initial IP
                    if current_ip != initial_ip:
                        logger.info(f"IP changed from initial: {initial_ip} -> {current_ip}")
                        return True, current_ip, adapter_id
                    return False, current_ip, adapter_id
                logger.warning("Auto-detect mode but no suitable adapters found")
                return False, None, None

            if not adapter_id:
                logger.debug("No network adapter configured in security.network section")
                return False, None, None

            logger.info(f"Checking IP for adapter {adapter_id!r} (initial: {initial_ip})")

            current_ip = self.get_adapter_ip(adapter_id)

            if current_ip is None:
                logger.warning(f"Adapter {adapter_id!r} not found or has no IP (was {initial_ip})")
                return True, None, adapter_id

            if current_ip != initial_ip:
                logger.info(f"IP changed for {adapter_id!r}: {initial_ip} -> {current_ip}")
                return True, current_ip, adapter_id

            logger.debug(f"IP unchanged for {adapter_id!r}: {current_ip}")
            return False, current_ip, adapter_id

        except (OSError, KeyError, AttributeError) as e:
            logger.error(f"IP change detection failed: {e}", exc_info=True)
            return False, None, None

    def get_recommended_adapter(self) -> tuple[str, str] | None:
        """Get recommended network adapter for LAN binding."""
        try:
            interfaces = psutil.net_if_addrs()
            interface_stats = psutil.net_if_stats()

            candidates = []

            for interface_name, addresses in interfaces.items():
                is_virtual = any(pattern.lower() in interface_name.lower() for pattern in self.virtual_patterns)
                is_loopback = any(pattern.lower() in interface_name.lower() for pattern in self.loopback_patterns)

                stats = interface_stats.get(interface_name)
                is_active = stats.isup if stats else False

                for addr in addresses:
                    if addr.family == 2:  # AF_INET
                        ip = addr.address

                        if not ip.startswith("127.") and is_active and not is_loopback:
                            candidates.append(
                                {
                                    "name": interface_name,
                                    "ip": ip,
                                    "is_virtual": is_virtual,
                                }
                            )

            if not candidates:
                logger.warning("No suitable network adapters found")
                return None

            physical = [c for c in candidates if not c["is_virtual"]]
            if physical:
                best = physical[0]
                return (best["name"], best["ip"])

            best = candidates[0]
            return (best["name"], best["ip"])

        except (OSError, KeyError, AttributeError) as e:
            logger.error(f"Failed to get recommended adapter: {e}", exc_info=True)
            return None
