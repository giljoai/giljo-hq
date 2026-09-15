# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import socket
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def get_network_ips(platform_handler: Optional[Any] = None) -> List[str]:
    ips = []

    try:
        import psutil

        logger.debug("Using psutil for network IP detection")
        addresses = psutil.net_if_addrs()

        for interface_addresses in addresses.values():
            for address in interface_addresses:
                if address.family == socket.AF_INET:
                    ip = address.address
                    if ip and ip != "127.0.0.1" and not ip.startswith("127."):
                        ips.append(ip)

        if ips:
            logger.info(f"Found {len(ips)} network IP(s) via psutil: {ips}")
            return ips

    except ImportError:
        logger.debug("psutil not available, trying fallback methods")
    except Exception as e:
        logger.warning(f"psutil IP detection failed: {e}")

    try:
        logger.debug("Using socket.gethostbyname() fallback")
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)

        if ip and ip != "127.0.0.1" and not ip.startswith("127."):
            ips.append(ip)
            logger.info(f"Found network IP via socket: {ip}")
            return ips

    except Exception as e:
        logger.warning(f"socket IP detection failed: {e}")

    if platform_handler and hasattr(platform_handler, "get_network_ips"):
        try:
            logger.debug("Using platform handler for network IP detection")
            handler_ips = platform_handler.get_network_ips()
            if handler_ips:
                logger.info(f"Found {len(handler_ips)} IP(s) via platform handler")
                return handler_ips
        except Exception as e:
            logger.warning(f"Platform handler IP detection failed: {e}")

    logger.warning("No network IPs detected - all methods failed")
    return []


def get_primary_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)

        s.connect(("8.8.8.8", 80))

        ip = s.getsockname()[0]
        s.close()

        if ip and ip != "127.0.0.1":
            logger.info(f"Primary IP detected: {ip}")
            return ip

    except Exception as e:
        logger.debug(f"Primary IP detection failed: {e}")

    return None


def validate_ip_address(ip: str) -> bool:
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False


def is_private_lan_host(host: str) -> bool:
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()

        return result != 0

    except Exception as e:
        logger.warning(f"Port availability check failed for {host}:{port}: {e}")
        return False


def get_network_adapters() -> List[dict]:
    adapters = []

    try:
        import psutil

        logger.debug("Using psutil for network adapter detection")
        addresses = psutil.net_if_addrs()
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
        loopback_patterns = ["lo", "Loopback"]

        for interface_name, interface_addresses in addresses.items():
            stats = interface_stats.get(interface_name)
            is_active = stats.isup if stats else False

            if not is_active:
                continue

            is_virtual = any(p.lower() in interface_name.lower() for p in virtual_patterns)
            is_loopback = any(p.lower() in interface_name.lower() for p in loopback_patterns)

            if is_loopback:
                continue

            for address in interface_addresses:
                if address.family == 2:
                    ip = address.address
                    if ip and ip != "127.0.0.1" and not ip.startswith("127."):
                        adapters.append({"name": interface_name, "ip": ip, "is_virtual": is_virtual})

        adapters.sort(key=lambda x: (x["is_virtual"], x["name"]))

        if adapters:
            logger.info(f"Found {len(adapters)} network adapter(s)")
            return adapters

    except ImportError:
        logger.debug("psutil not available for adapter detection")
    except Exception as e:
        logger.warning(f"Network adapter detection failed: {e}")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "127.0.0.1" and not ip.startswith("127."):
            logger.info(f"Fallback: detected primary IP {ip} via UDP socket")
            return [{"name": "Primary Network", "ip": ip, "is_virtual": False}]
    except Exception as e:
        logger.debug(f"UDP socket fallback failed: {e}")

    return []


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception as e:
        logger.warning(f"Hostname detection failed: {e}")
        return "localhost"


def resolve_hostname(hostname: str) -> Optional[str]:
    try:
        return socket.gethostbyname(hostname)
    except Exception as e:
        logger.warning(f"Hostname resolution failed for {hostname}: {e}")
        return None
