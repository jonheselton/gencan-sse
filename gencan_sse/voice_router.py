"""IP-based voice routing for gencan-sse.

Provides dynamic sticky voice assignments per IP address, with an inactivity timeout.
"""

import logging
import random
import time

logger = logging.getLogger(__name__)

class VoiceRouter:
    """Dynamically assigns and remembers a distinct voice for each IP address.
    
    Assignments expire after a configured number of hours of inactivity.
    """
    
    def __init__(self, voice_pool: list[str], timeout_hours: float = 2.0):
        self._voice_pool = voice_pool or ["Zoe (Premium)"]
        self._timeout_seconds = timeout_hours * 3600
        # Map of IP -> {"voice": str, "last_seen": float}
        self._assignments: dict[str, dict] = {}
        
    def get_voice_for_ip(self, ip: str) -> str:
        """Get the assigned voice for an IP, generating a new one if necessary.
        
        Args:
            ip: The client IP address.
            
        Returns:
            The name of the voice assigned to this IP.
        """
        now = time.time()
        self._cleanup_expired(now)
        
        if ip in self._assignments:
            self._assignments[ip]["last_seen"] = now
            return self._assignments[ip]["voice"]
            
        # Assign a new voice
        # Try to pick one that isn't currently used if possible
        used_voices = {data["voice"] for data in self._assignments.values()}
        available_voices = [v for v in self._voice_pool if v not in used_voices]
        
        if available_voices:
            voice = random.choice(available_voices)
        else:
            # Fall back to picking randomly from the full pool if all are used
            voice = random.choice(self._voice_pool)
            
        self._assignments[ip] = {
            "voice": voice,
            "last_seen": now
        }
        logger.info("Assigned premium voice '%s' to new IP: %s", voice, ip)
        
        return voice
        
    def _cleanup_expired(self, now: float) -> None:
        """Remove assignments that have expired."""
        expired_ips = [
            ip for ip, data in self._assignments.items()
            if (now - data["last_seen"]) > self._timeout_seconds
        ]
        for ip in expired_ips:
            voice = self._assignments.pop(ip)["voice"]
            logger.info("Released voice '%s' from expired IP: %s", voice, ip)
