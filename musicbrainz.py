"""
MusicBrainz API module for accessing music metadata.
"""

import random
import time
from typing import Dict, List, Optional, Set
import requests
from abc import ABC, abstractmethod
from colorama import Fore, Style


# Constants
DEFAULT_RELEASES_LIMIT = 3
BASE_REQUEST_DELAY = 6  # seconds between API requests
DEFAULT_RECOMMENDATION_LIMIT = 50


def normalize_artist_name(name: str) -> str:
    """
    Normalize an artist name for consistent comparison.
    
    Args:
        name (str): Artist name to normalize
        
    Returns:
        str: Normalized artist name (lowercase, no special chars, no 'the' prefix)
    """
    if not name:
        return ""
        
    # Convert to lowercase and strip whitespace
    name = name.lower().strip()
    
    # Remove 'the ' prefix if it exists
    if name.startswith('the '):
        name = name[4:]
    
    # Replace ampersands and 'and' for consistency
    name = name.replace(' & ', ' and ')
    
    # Remove special characters, keeping only alphanumeric and space
    name = ''.join(c for c in name if c.isalnum() or c.isspace()).strip()
    
    return name


class MusicDatabase(ABC):
    """Abstract base class for music database APIs."""
    
    @abstractmethod
    def search_artist(self, artist_name: str) -> Optional[Dict]:
        """
        Search for an artist in the database.
        
        Args:
            artist_name (str): Name of the artist to search for
            
        Returns:
            Optional[Dict]: Artist information or None if not found
        """
        pass
    
    @abstractmethod
    def get_similar_artists(self, artist_id: str, limit: int, exclude_set: Optional[Set[str]] = None) -> List[Dict]:
        """
        Get similar artists from the database.
        
        Args:
            artist_id (str): ID of the artist to find similar artists for
            limit (int): Maximum number of similar artists to return
            exclude_set (Optional[Set[str]]): Set of artist names to exclude from results
            
        Returns:
            List[Dict]: List of similar artist dictionaries
        """
        pass
    
    @abstractmethod
    def get_artist_releases(self, artist_id: str, limit: int) -> List[Dict]:
        """
        Get releases for an artist from the database.
        
        Args:
            artist_id (str): ID of the artist
            limit (int): Maximum number of releases to return
            
        Returns:
            List[Dict]: List of release dictionaries
        """
        pass
    
    @abstractmethod
    def get_artist_genres(self, artist_id: str) -> List[str]:
        """
        Get genre tags for an artist from the database.
        
        Args:
            artist_id (str): ID of the artist
            
        Returns:
            List[str]: List of genre names
        """
        pass


class MusicBrainzAPI(MusicDatabase):
    """MusicBrainz API implementation."""
    
    def __init__(self, user_email: str = "<insert your email here>"):
        """
        Initialize the MusicBrainz API client.
        
        Args:
            user_email (str): Email to use in User-Agent (MusicBrainz etiquette)
        """
        self.base_url = "https://musicbrainz.org/ws/2/"
        self.headers = {
            'User-Agent': f'FindNewFLACArtists/1.0 ({user_email})',
            'Accept': 'application/json'
        }
        # Keep track of consecutive failures for adaptive backoff
        self.consecutive_failures = 0
        self.current_delay = BASE_REQUEST_DELAY

    def _make_api_request(self, url: str, params: Dict, error_context: str) -> Optional[Dict]:
        """
        Make an API request with retry logic and exponential backoff.
        
        Args:
            url (str): API endpoint URL
            params (Dict): Query parameters
            error_context (str): Context for error messages
            
        Returns:
            Optional[Dict]: API response as a dictionary or None on failure
        """
        base_delay = 1  # Initial delay
        max_delay = 64  # Maximum delay
        attempt = 0
        max_retries = 5  # Max retries

        while attempt < max_retries:
            try:
                response = requests.get(url, headers=self.headers, params=params)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in (429, 503, 504):  # Handle rate limits and server availability
                    wait_time = base_delay * (2 ** attempt)  # Exponential backoff
                    wait_time = min(wait_time, max_delay)
                    print(f"API rate limit or service unavailable. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    attempt += 1
                else:
                    print(f"HTTP Error {response.status_code} for {error_context}: {response.text}")
                    break  # Non-retriable HTTP error
            except requests.exceptions.RequestException as e:
                if attempt >= max_retries - 1:
                    print(f"Failed to complete request after {max_retries} attempts due to network error: {e}")
                    break
                else:
                    wait_time = base_delay * (2 ** attempt)
                    wait_time = min(wait_time, max_delay)
                    print(f"Network error encountered: {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    attempt += 1
            except KeyboardInterrupt:
                print("Operation cancelled by user.")
                break

        return None

    def search_artist(self, artist_name: str) -> Optional[Dict]:
        """
        Search for an artist on MusicBrainz.
        
        Args:
            artist_name (str): Name of the artist to search for
            
        Returns:
            Optional[Dict]: Artist information or None if not found
        """
        params = {
            'query': f'artist:"{artist_name}"',
            'limit': 1,
            'fmt': 'json'
        }
        
        result = self._make_api_request(
            f"{self.base_url}artist", 
            params, 
            f"Error searching for artist {artist_name}"
        )
        
        if result and result.get('artists') and len(result['artists']) > 0:
            return result['artists'][0]
        else:
            if result:  # Request succeeded but no artists found
                print(f"{Fore.YELLOW}No artist found for {artist_name}{Style.RESET_ALL}")
            return None
    
    def get_similar_artists(self, artist_id: str, limit: int = DEFAULT_RECOMMENDATION_LIMIT, 
                         exclude_set: Optional[Set[str]] = None) -> List[Dict]:
        """
        Comprehensive method to find similar artists using multiple strategies.
        
        Args:
            artist_id (str): MusicBrainz ID of the artist
            limit (int): Maximum number of similar artists to return
            exclude_set (Optional[Set[str]]): Set of normalized artist names to exclude from results
            
        Returns:
            List[Dict]: List of similar artist dictionaries
        """
        # Initialize exclusion set
        exclude_set = exclude_set or set()
        
        # Multiple recommendation strategies
        recommendation_strategies = [
            self._get_related_artists,
            self._search_by_genre,
            self._search_by_name_pattern
        ]
        
        # Collect similar artists
        all_similar_artists = []
        
        # Track used artist names to prevent duplicates
        used_artist_names = set()
        
        # Try each strategy
        for strategy in recommendation_strategies:
            try:
                # Fetch similar artists using current strategy
                similar_artists = strategy(artist_id)
                
                # Filter and deduplicate artists
                for artist in similar_artists:
                    artist_name = artist.get('name', '')
                    normalized_name = normalize_artist_name(artist_name)
                    
                    # Skip if:
                    # 1. Name is empty
                    # 2. Already used
                    # 3. In exclude set
                    if (not artist_name or 
                        normalized_name in used_artist_names or 
                        normalized_name in exclude_set):
                        continue
                    
                    # Add to used names and similar artists
                    used_artist_names.add(normalized_name)
                    all_similar_artists.append(artist)
                    
                    # Stop if we've reached the limit
                    if len(all_similar_artists) >= limit:
                        break
                
                # Stop searching if we've found enough artists
                if len(all_similar_artists) >= limit:
                    break
            
            except Exception as e:
                print(f"{Fore.RED}Strategy failed: {e}{Style.RESET_ALL}")
        
        return all_similar_artists[:limit]

    def _get_related_artists(self, artist_id: str) -> List[Dict]:
        """
        Fetch artists directly related through MusicBrainz relationships.
        
        Args:
            artist_id (str): MusicBrainz ID of the source artist
            
        Returns:
            List[Dict]: List of related artist dictionaries
        """
        # Fetch artist relationships
        params = {
            'inc': 'artist-rels',
            'fmt': 'json'
        }
        
        result = self._make_api_request(
            f"{self.base_url}artist/{artist_id}", 
            params, 
            f"Error fetching artist relations for {artist_id}"
        )
        
        if not result or 'relations' not in result:
            return []
        
        # Filter and collect related artists
        related_artists = []
        for relation in result['relations']:
            # Look for meaningful relationship types
            if relation.get('type') in ['similar to', 'influenced by', 'collaborated with']:
                artist = relation.get('artist', {})
                if artist:
                    related_artists.append(artist)
        
        return related_artists

    def _search_by_genre(self, artist_id: str) -> List[Dict]:
        """
        Search for artists with similar genres.
        
        Args:
            artist_id (str): MusicBrainz ID of the source artist
            
        Returns:
            List[Dict]: List of genre-similar artist dictionaries
        """
        # Get source artist genres
        genres_result = self._make_api_request(
            f"{self.base_url}artist/{artist_id}", 
            {'inc': 'genres', 'fmt': 'json'}, 
            f"Error fetching genres for {artist_id}"
        )
        
        # Extract genres
        genres = [genre['name'] for genre in genres_result.get('genres', [])] if genres_result else []
        
        if not genres:
            return []
        
        # Search artists by first genre
        genre_search_result = self._make_api_request(
            f"{self.base_url}artist", 
            {
                'query': f'tag:"{genres[0]}"',
                'limit': 50,
                'fmt': 'json'
            },
            f"Error searching for genre {genres[0]}"
        )
        
        return genre_search_result.get('artists', []) if genre_search_result else []

    def _search_by_name_pattern(self, artist_id: str) -> List[Dict]:
        """
        Search for artists with similar name patterns.
        
        Args:
            artist_id (str): MusicBrainz ID of the source artist
            
        Returns:
            List[Dict]: List of name-similar artist dictionaries
        """
        # Fetch source artist name
        artist_result = self._make_api_request(
            f"{self.base_url}artist/{artist_id}", 
            {'fmt': 'json'}, 
            f"Error fetching artist name for {artist_id}"
        )
        
        if not artist_result or 'name' not in artist_result:
            return []
        
        # Extract search words from artist name
        name = artist_result['name']
        name_words = [word for word in name.split() if len(word) > 3]
        
        if not name_words:
            return []
        
        # Search by first meaningful word
        name_search_result = self._make_api_request(
            f"{self.base_url}artist", 
            {
                'query': f'artist:{name_words[0]}',
                'limit': 50,
                'fmt': 'json'
            },
            f"Error searching for similar names"
        )
        
        return name_search_result.get('artists', []) if name_search_result else []
    
    def get_artist_releases(self, artist_id: str, limit: int = DEFAULT_RELEASES_LIMIT) -> List[Dict]:
        """
        Get releases for an artist from MusicBrainz.
        
        Args:
            artist_id (str): ID of the artist
            limit (int): Maximum number of releases to return
            
        Returns:
            List[Dict]: List of release dictionaries
        """
        params = {
            'artist': artist_id,
            'limit': limit,
            'fmt': 'json'
        }
        
        result = self._make_api_request(
            f"{self.base_url}release", 
            params, 
            f"Error getting releases for {artist_id}"
        )
        
        return result.get('releases', []) if result else []
    
    def get_artist_genres(self, artist_id: str) -> List[str]:
        """
        Get genre tags for an artist from MusicBrainz.
        
        Args:
            artist_id (str): ID of the artist
            
        Returns:
            List[str]: List of genre names
        """
        params = {
            'inc': 'genres',
            'fmt': 'json'
        }
        
        result = self._make_api_request(
            f"{self.base_url}artist/{artist_id}", 
            params, 
            f"Error getting genres for {artist_id}"
        )
        
        return [genre['name'] for genre in result.get('genres', [])] if result else []