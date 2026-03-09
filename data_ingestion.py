"""
DEX market data ingestion with triangulation and validation.
Supports multiple exchanges via CCXT with WebSocket fallback.
Implements data consistency checks and outlier detection.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

import ccxt
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest

from firebase_config import get_firestore
from event_schema import MarketDataEvent, EventValidator, AssetType

logger = logging.getLogger(__name__)


class DEXDataIngestor:
    """
    Ingests market data from multiple DEX sources with triangulation.
    Implements consistency checks, outlier detection, and Firestore storage.
    """
    
    def __init__(self, target_symbols: List[str] = None):
        """
        Initialize DEX data ingestor.
        
        Args:
            target_symbols: List of symbols to monitor (e.g., ['ETH/USDC', 'DEGEN/USDC'])
        """
        self.db = get_firestore()
        self.target_symbols = target_symbols or ['ETH/USDC', 'DEGEN/USDC', 'BRETT/USDC']
        
        # Configure exchanges (Base L2 DEXs)
        self.exchanges = {
            'uniswap': self._init_uniswap_client(),
            'pancakeswap': ccxt.pancakeswap(),
            'sushiswap': ccxt.sushiswap(),
        }
        
        # Remove exchanges that fail initialization
        self.exchanges = {k: v for k, v in self.exchanges.items() if v}
        
        # Data validation thresholds
        self.price_tolerance = 0.02  # 2% price difference allowed
        self.min_sources = 2
        self.outlier_contamination = 0.1
        
        # State tracking
        self.last_prices: Dict[str, Dict[str, float]] = defaultdict(dict)
        self.price_history: Dict[str, List[float]] = defaultdict(list)
        self.source_health: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        logger.info(f"DEXDataIngestor initialized with {len(self.exchanges)} exchanges")
    
    def _init_uniswap_client(self) -> Optional[ccxt.Exchange]:
        """Initialize Uniswap client with custom configuration."""
        try:
            # CCXT doesn't have native Uniswap v3 support for all functions
            # We'll use a generic DEX configuration
            exchange = ccxt.Exchange({
                'id': 'uniswap',
                'name': 'Uniswap',
                'urls': {
                    'api': 'https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3'
                },
                'version': 'v3',
                'rateLimit': 1000,
            })
            return exchange
        except Exception as e:
            logger.warning(f"Failed to initialize Uniswap client: {e}")
            return None
    
    async def fetch_market_data(self, symbol: str) -> List[MarketDataEvent]:
        """
        Fetch market