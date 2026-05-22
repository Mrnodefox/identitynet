"""
Distributed Node Manager for IdentityNet
Peer discovery, pubsub message handling, and cross-node data synchronization.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import threading
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

try:
    import ipfshttpclient

    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class DistributedNodeManager:
    """Manages distributed node communication and data synchronization."""

    def __init__(self, node_id: str = None):
        self.node_id = node_id or self._generate_node_id()
        self.peers: Set[str] = set()
        self.global_username_registry: Dict[str, Dict[str, str]] = {}
        self.global_did_registry: Dict[str, Dict[str, str]] = {}
        self.global_public_keys: Dict[str, str] = {}  # did -> public_key
        self.ipfs_client = None
        self.pubsub_topic = "identitynet-global-registry"
        self._running = False
        self._listener_thread: Optional[threading.Thread] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None
        self._handlers: Dict[str, MessageHandler] = {}
        self._seen_messages: Set[str] = set()

    def _generate_node_id(self) -> str:
        timestamp = datetime.utcnow().isoformat()
        hash_input = f"{timestamp}-{hash(timestamp)}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def on(self, message_type: str, handler: MessageHandler) -> None:
        self._handlers[message_type] = handler

    async def initialize(self) -> bool:
        if not IPFS_AVAILABLE:
            logger.warning("IPFS not available. Running in standalone mode.")
            return False

        try:
            self.ipfs_client = ipfshttpclient.connect("/ip4/127.0.0.1/tcp/5001")
            try:
                self.ipfs_client.pubsub.peers()
                logger.info("IPFS pubsub available")
            except Exception:
                logger.warning(
                    "IPFS pubsub not available. Enable: ipfs daemon --enable-pubsub-experiment"
                )
                return False

            self.ipfs_client.pubsub.subscribe(self.pubsub_topic)
            self._running = True
            self._loop = asyncio.get_running_loop()
            self._listener_thread = threading.Thread(
                target=self._pubsub_listener_loop, daemon=True, name="pubsub-listener"
            )
            self._listener_thread.start()
            self._processor_task = asyncio.create_task(self._process_message_queue())
            await self._announce_node()
            logger.info("Node %s initialized successfully", self.node_id)
            return True
        except Exception as e:
            logger.error("Failed to initialize node: %s", e)
            return False

    def _pubsub_listener_loop(self) -> None:
        """Blocking IPFS pubsub subscription — forwards messages to asyncio queue."""
        while self._running and self.ipfs_client:
            try:
                with self.ipfs_client.pubsub.subscribe(self.pubsub_topic) as subscription:
                    for raw_msg in subscription:
                        if not self._running:
                            break
                        parsed = self._parse_pubsub_message(raw_msg)
                        if parsed:
                            if getattr(self, "_loop", None):
                                self._loop.call_soon_threadsafe(
                                    self._message_queue.put_nowait, parsed
                                )
            except Exception as e:
                logger.error("Pubsub listener error: %s", e)
                if self._running:
                    threading.Event().wait(5)

    def _parse_pubsub_message(self, raw_msg: Any) -> Optional[Dict[str, Any]]:
        try:
            if isinstance(raw_msg, dict):
                data_field = raw_msg.get("data")
                sender = raw_msg.get("from", raw_msg.get("from_id"))
            else:
                return None

            if not data_field:
                return None

            if isinstance(data_field, str):
                try:
                    decoded = base64.b64decode(data_field)
                except Exception:
                    decoded = data_field.encode("utf-8")
            else:
                decoded = data_field

            message = json.loads(decoded.decode("utf-8"))
            if sender:
                self.peers.add(str(sender))
            return message
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            logger.debug("Skipping unparseable pubsub message: %s", e)
            return None

    async def _process_message_queue(self) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )
                await self._handle_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Message processor error: %s", e)

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        msg_id = message.get("message_id")
        if msg_id:
            if msg_id in self._seen_messages:
                return
            self._seen_messages.add(msg_id)
            if len(self._seen_messages) > 10000:
                self._seen_messages = set(list(self._seen_messages)[-5000:])

        if message.get("node_id") == self.node_id:
            return

        msg_type = message.get("type")
        handler = self._handlers.get(msg_type)
        if handler:
            await handler(message)
            return

        if msg_type == "node_announce":
            self.peers.add(message.get("node_id", ""))
        elif msg_type == "username_register":
            await self._apply_username_register(message)
        elif msg_type == "user_sync":
            await self._apply_user_sync(message)
        elif msg_type == "ledger_tx":
            await self._apply_ledger_tx(message)
        elif msg_type == "attestation_sync":
            await self._apply_attestation_sync(message)
        elif msg_type == "agent_parliament":
            handler = self._handlers.get("agent_parliament")
            if handler:
                await handler(message)

    async def _apply_username_register(self, message: Dict[str, Any]) -> None:
        username = message.get("username")
        did = message.get("did")
        node_id = message.get("node_id")
        public_key = message.get("public_key")
        if not username or not did:
            return

        existing = self.global_username_registry.get(username)
        if existing and existing.get("did") != did:
            logger.warning(
                "Username conflict: %s claimed by %s and %s",
                username,
                existing.get("did"),
                did,
            )
            return

        self.global_username_registry[username] = {
            "did": did,
            "node_id": node_id,
            "timestamp": message.get("timestamp", ""),
        }
        self.global_did_registry[did] = {
            "username": username,
            "node_id": node_id,
        }
        if public_key:
            self.global_public_keys[did] = public_key

    async def _apply_user_sync(self, message: Dict[str, Any]) -> None:
        user_data = message.get("user_data", {})
        did = user_data.get("did")
        username = user_data.get("username")
        if did:
            self.global_did_registry[did] = {
                "username": username,
                "node_id": message.get("node_id"),
            }
            pub = user_data.get("public_key")
            if pub:
                self.global_public_keys[did] = pub
        if username and did:
            self.global_username_registry[username] = {
                "did": did,
                "node_id": message.get("node_id"),
                "timestamp": message.get("timestamp", ""),
            }
        handler = self._handlers.get("user_sync")
        if handler:
            await handler(message)

    async def _apply_ledger_tx(self, message: Dict[str, Any]) -> None:
        handler = self._handlers.get("ledger_tx")
        if handler:
            await handler(message)

    async def _apply_attestation_sync(self, message: Dict[str, Any]) -> None:
        handler = self._handlers.get("attestation_sync")
        if handler:
            await handler(message)

    async def _announce_node(self) -> None:
        await self._publish_message(
            {
                "type": "node_announce",
                "node_id": self.node_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def _publish_message(self, message: dict) -> bool:
        if not self.ipfs_client:
            return False
        try:
            message["message_id"] = hashlib.sha256(
                json.dumps(message, sort_keys=True).encode()
            ).hexdigest()[:24]
            message["node_id"] = self.node_id
            message_json = json.dumps(message)
            self.ipfs_client.pubsub.publish(self.pubsub_topic, message_json)
            return True
        except Exception as e:
            logger.error("Failed to publish message: %s", e)
            return False

    async def register_username(
        self, username: str, did: str, public_key: str
    ) -> bool:
        if username in self.global_username_registry:
            entry = self.global_username_registry[username]
            if entry.get("did") != did:
                return False

        self.global_username_registry[username] = {
            "did": did,
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.global_did_registry[did] = {
            "username": username,
            "node_id": self.node_id,
        }
        self.global_public_keys[did] = public_key

        return await self._publish_message(
            {
                "type": "username_register",
                "username": username,
                "did": did,
                "public_key": public_key,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def check_username_available(self, username: str) -> bool:
        return username not in self.global_username_registry

    async def sync_user_data(self, user_data: dict) -> None:
        await self._publish_message(
            {
                "type": "user_sync",
                "user_data": user_data,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def broadcast_ledger_tx(self, tx: dict) -> None:
        await self._publish_message({"type": "ledger_tx", "transaction": tx})

    async def broadcast_attestation(self, attestation: dict) -> None:
        await self._publish_message(
            {
                "type": "attestation_sync",
                "attestation": attestation,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def broadcast_agent_parliament(self, payload: dict) -> None:
        await self._publish_message(
            {
                "type": "agent_parliament",
                **payload,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def get_peers(self) -> List[str]:
        if not self.ipfs_client:
            return []
        try:
            peers = self.ipfs_client.pubsub.peers(self.pubsub_topic)
            return list(peers)
        except Exception as e:
            logger.error("Failed to get peers: %s", e)
            return []

    async def shutdown(self) -> None:
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=3)
        if self.ipfs_client:
            try:
                self.ipfs_client.pubsub.unsubscribe(self.pubsub_topic)
            except Exception as e:
                logger.error("Error during shutdown: %s", e)


node_manager = DistributedNodeManager()
