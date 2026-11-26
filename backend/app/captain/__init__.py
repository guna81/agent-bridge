"""AgentBridge Captain: project-scoped multi-CLI orchestrator, worktrees, and channels."""
from .bus import MissionEventBus, NotificationEvent
from .channels import ChannelDispatcher
from .orchestrator import CaptainOrchestrator

__all__ = ["MissionEventBus", "NotificationEvent", "ChannelDispatcher", "CaptainOrchestrator"]
