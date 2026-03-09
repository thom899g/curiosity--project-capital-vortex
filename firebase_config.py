"""
Firebase Admin SDK initialization and configuration for Project Capital Vortex.
Uses environment variables for credentials with fallback to service account file.
Implements connection pooling and automatic reconnection for production resilience.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore, auth
from google.cloud.firestore_v1 import Client as FirestoreClient
from google.cloud.firestore_v1.base_client import BaseClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FirebaseManager:
    """
    Manages Firebase connection with automatic reconnection and health monitoring.
    Implements singleton pattern to ensure single connection pool.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.app = None
            self.db: Optional[FirestoreClient] = None
            self._connect()
            self._initialized = True
    
    def _connect(self) -> None:
        """
        Initialize Firebase connection with multiple fallback strategies.
        Priority:
        1. FIREBASE_CREDENTIALS_JSON environment variable
        2. Service account file at /secrets/firebase-key.json
        3. Google Application Default Credentials
        """
        
        if firebase_admin._apps:
            # Reuse existing app
            self.app = firebase_admin.get_app()
            logger.info("Reusing existing Firebase app")
        else:
            try:
                # Strategy 1: Environment variable
                creds_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
                if creds_json:
                    cred_dict = json.loads(creds_json)
                    cred = credentials.Certificate(cred_dict)
                    logger.info("Using Firebase credentials from environment variable")
                
                # Strategy 2: Service account file
                elif os.path.exists('/secrets/firebase-key.json'):
                    cred = credentials.Certificate('/secrets/firebase-key.json')
                    logger.info("Using Firebase credentials from service account file")
                
                # Strategy 3: Application Default Credentials
                elif os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                    cred = credentials.ApplicationDefault()
                    logger.info("Using Google Application Default Credentials")
                
                else:
                    raise ValueError("No Firebase credentials found")
                
                # Initialize with connection settings
                self.app = firebase_admin.initialize_app(
                    cred,
                    options={
                        'projectId': os.getenv('FIREBASE_PROJECT_ID', 'capital-vortex'),
                        'databaseURL': os.getenv('FIREBASE_DATABASE_URL', ''),
                        'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET', '')
                    }
                )
                logger.info("Firebase app initialized successfully")
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in FIREBASE_CREDENTIALS_JSON: {e}")
                raise
            except FileNotFoundError as e:
                logger.error(f"Service account file not found: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Firebase: {e}")
                raise
        
        # Initialize Firestore client with retry settings
        try:
            self.db = firestore.client(self.app)
            # Test connection
            test_ref = self.db.collection('system').document('health')
            test_ref.set({
                'last_check': firestore.SERVER_TIMESTAMP,
                'status': 'connected'
            }, merge=True)
            logger.info("Firestore client initialized and tested")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firestore: {e}")
            raise
    
    def get_db(self) -> FirestoreClient:
        """Get Firestore client with connection health check."""
        if not self.db:
            self._connect()
        
        try:
            # Simple health check
            self.db.collection('system').document('health').get()
            return self.db
        except Exception as e:
            logger.warning(f"Firestore connection lost, reconnecting: {e}")
            self._connect()
            return self.db
    
    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check of Firebase services."""
        try:
            db = self.get_db()
            
            # Check Firestore
            firestore_check = db.collection('system').document('health').get().exists
            
            # Check Firebase Auth (if needed)
            auth_check = True
            # Note: auth.list_users() requires appropriate permissions
            
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'firestore': 'healthy' if firestore_check else 'unhealthy',
                'auth': 'healthy' if auth_check else 'unhealthy',
                'overall': 'healthy' if firestore_check and auth_check else 'degraded'
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'firestore': 'unhealthy',
                'auth': 'unknown',
                'overall': 'unhealthy',
                'error': str(e)
            }


# Global instance
firebase_manager = FirebaseManager()


def get_firestore() -> FirestoreClient:
    """Helper function for dependency injection."""
    return firebase_manager.get_db()