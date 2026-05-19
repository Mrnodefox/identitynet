"""
Distributed Node Manager for IdentityNet
Handles peer discovery, communication, and data synchronization across nodes
"""

import asyncio
import json
import hashlib
from typing import Dict, List, Optional, Set
from datetime import datetime
import logging

try:
    import ipfshttpclient
    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DistributedNodeManager:
    """Manages distributed node communication and data synchronization"""
    
    def __init__(self, node_id: str = None):
        self.node_id = node_id or self._generate_node_id()
        self.peers: Set[str] = set()
        self.global_username_registry: Dict[str, str] = {}  # username -> node_id
        self.global_did_registry: Dict[str, str] = {}  # did -> node_id
        self.ipfs_client = None
        self.pubsub_topic = "identitynet-global-registry"
        self._running = False
        
    def _generate_node_id(self) -> str:
        """Generate unique node ID"""
        timestamp = datetime.utcnow().isoformat()
        hash_input = f"{timestamp}-{hash(timestamp)}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    async def initialize(self):
        """Initialize IPFS connection and pubsub"""
        if not IPFS_AVAILABLE:
            logger.warning("IPFS not available. Running in standalone mode.")
            return False
            
        try:
            self.ipfs_client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
            
            # Check if pubsub is available
            try:
                self.ipfs_client.pubsub.peers()
                logger.info("IPFS pubsub available")
            except Exception:
                logger.warning("IPFS pubsub not available. Enable with: ipfs daemon --enable-pubsub-experiment")
                return False
                
            # Subscribe to global registry topic
            await self._subscribe_to_registry()
            
            # Announce this node to the network
            await self._announce_node()
            
            self._running = True
            logger.info(f"Node {self.node_id} initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize node: {e}")
            return False
    
    async def _subscribe_to_registry(self):
        """Subscribe to global registry pubsub topic"""
        try:
            # Subscribe to the topic
            self.ipfs_client.pubsub.subscribe(self.pubsub_topic)
            logger.info(f"Subscribed to topic: {self.pubsub_topic}")
            
            # Start listening for messages in background
            asyncio.create_task(self._listen_for_messages())
            
        except Exception as e:
            logger.error(f"Failed to subscribe to pubsub: {e}")
    
    async def _listen_for_messages(self):
        """Listen for pubsub messages from other nodes"""
        while self._running:
            try:
                # Get messages from pubsub
                messages = self.ipfs_client.pubsub.peers()
                
                # Process incoming messages
                # Note: This is a simplified implementation
                # In production, you'd use proper message queue handling
                
                await asyncio.sleep(1)  # Prevent busy waiting
                
            except Exception as e:
                logger.error(f"Error listening for messages: {e}")
                await asyncio.sleep(5)
    
    async def _announce_node(self):
        """Announce this node to the network"""
        message = {
            "type": "node_announce",
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._publish_message(message)
    
    async def _publish_message(self, message: dict):
        """Publish message to the global registry"""
        if not self.ipfs_client:
            logger.warning("IPFS not available, cannot publish message")
            return False
            
        try:
            message_json = json.dumps(message)
            self.ipfs_client.pubsub.publish(self.pubsub_topic, message_json)
            logger.debug(f"Published message: {message.get('type')}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False
    
    async def register_username(self, username: str, did: str) -> bool:
        """Register username in global registry"""
        # Check if username is already taken globally
        if username in self.global_username_registry:
            logger.warning(f"Username {username} already taken globally")
            return False
        
        # Register locally
        self.global_username_registry[username] = self.node_id
        self.global_did_registry[did] = self.node_id
        
        # Broadcast to network
        message = {
            "type": "username_register",
            "username": username,
            "did": did,
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        success = await self._publish_message(message)
        if success:
            logger.info(f"Username {username} registered globally")
        
        return success
    
    async def check_username_available(self, username: str) -> bool:
        """Check if username is available globally"""
        # In a real implementation, this would query the network
        # For now, check local registry
        return username not in self.global_username_registry
    
    async def sync_user_data(self, user_data: dict):
        """Sync user data across nodes"""
        message = {
            "type": "user_sync",
            "user_data": user_data,
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self._publish_message(message)
    
    async def get_peers(self) -> List[str]:
        """Get list of connected peers"""
        if not self.ipfs_client:
            return []
        
        try:
            peers = self.ipfs_client.pubsub.peers(self.pubsub_topic)
            return list(peers)
        except Exception as e:
            logger.error(f"Failed to get peers: {e}")
            return []
    
    async def shutdown(self):
        """Shutdown the node manager"""
        self._running = False
        if self.ipfs_client:
            try:
                # Unsubscribe from topic
                self.ipfs_client.pubsub.unsubscribe(self.pubsub_topic)
                logger.info("Unsubscribed from pubsub topic")
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")


# Global node manager instance
node_manager = DistributedNodeManager()
