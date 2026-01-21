"""
Event Bus for Inter-Module Communication

Simple async event bus for decoupling modules
"""

import asyncio
from typing import Dict, List, Callable, Any, Awaitable, Optional
from dataclasses import dataclass

from ..common.logging import get_logger

logger = get_logger('eventbus')


@dataclass
class Event:
    """Base Event class"""
    type: str
    data: Dict[str, Any]


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """
    Simple Event Bus

    Allows modules to publish/subscribe to events without tight coupling
    """

    def __init__(self):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def subscribe(self, event_type: str, handler: EventHandler):
        """Subscribe to event type"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(handler)
        logger.debug("Handler subscribed", event_type=event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler):
        """Unsubscribe from event type"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                logger.debug("Handler unsubscribed", event_type=event_type)
            except ValueError:
                pass

    async def publish(self, event: Event):
        """Publish event to all subscribers"""
        event_type = event.type if hasattr(event, 'type') else str(event.__class__.__name__)

        logger.debug("Event published", event_type=event_type)

        # Get subscribers for this event type
        handlers = self._subscribers.get(event_type, [])

        # Call handlers asynchronously
        if handlers:
            tasks = [handler(event) for handler in handlers]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self):
        """Start event bus processing (if needed)"""
        self._running = True
        logger.info("EventBus started")

    async def stop(self):
        """Stop event bus"""
        self._running = False
        logger.info("EventBus stopped")
