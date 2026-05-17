"""
Database Module
Handles MongoDB connection and collection management.
"""

import os
import certifi
from pymongo import MongoClient, ASCENDING
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class Database:
    """MongoDB database wrapper with collections for the bot."""
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db = None
        self.conversations = None
        self.reminders = None
        self.rates = None
        self.giveaways = None
        self.invites = None
        self.sticky_pins = None
        self._connected = False
    
    def connect(self) -> bool:
        """Initialize MongoDB connection and collections."""
        mongo_uri = os.getenv("MONGO_URI")
        
        if not mongo_uri:
            print("[!] MONGO_URI not found. MongoDB disabled.")
            return False
        
        try:
            self.client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
            self.db = self.client.ai_bot
            
            # Initialize collections
            self.conversations = self.db.conversations
            self.reminders = self.db.reminders
            self.rates = self.db.rates
            self.giveaways = self.db.giveaways
            self.invites = self.db.invites
            self.sticky_pins = self.db.sticky_pins
            
            # Create indexes
            self._create_indexes()
            
            self._connected = True
            print("✅ Connected to MongoDB")
            return True
            
        except Exception as e:
            print(f"[!] MongoDB connection failed: {e}")
            self._connected = False
            return False
    
    def _create_indexes(self):
        """Create necessary indexes for collections."""
        # TTL index for conversations (7 days)
        self.conversations.create_index("timestamp", expireAfterSeconds=604800)
        
        # TTL index for reminders (30 days)
        self.reminders.create_index("reminder_time", expireAfterSeconds=2592000)
        
        # Unique index for guild rates
        self.rates.create_index([("guild_id", ASCENDING)], unique=True)
        
        # Compound index for invite tracking
        self.invites.create_index(
            [("guild_id", ASCENDING), ("user_id", ASCENDING)], unique=True
        )

        # Indexes for sticky pins
        self.sticky_pins.create_index([("guild_id", ASCENDING)])
        self.sticky_pins.create_index([("pin_id", ASCENDING)], unique=True)
    
    @property
    def is_connected(self) -> bool:
        return self._connected


# Global database instance
db = Database()
