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
BASE_REQUEST_DELAY = 2  # seconds between API requests
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

    def _make_api_request(self, url: str, params: Dict, context: str) -> Optional[Dict]:
        """
        Make an API request with detailed retry and success logging.
        
        Args:
            url (str): API endpoint URL
            params (Dict): Query parameters
            context (str): Context for log messages
            
        Returns:
            Optional[Dict]: API response as a dictionary or None on failure
        """
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # Prepare a readable context
                readable_context = context
                if 'query' in params:
                    if 'artist:' in params['query']:
                        readable_context = params['query'].split('artist:"')[1].split('"')[0]
                    elif 'tag:' in params['query']:
                        readable_context = params['query'].split('tag:"')[1].split('"')[0]
                
                # Log attempt start
                print(f"{Fore.YELLOW}Attempt {attempt + 1} of {max_retries} for {readable_context}")
                print(f"Request URL: {url}")
                print(f"Request Params: {params}{Style.RESET_ALL}")
                
                # Wait 6 seconds between attempts
                print(f"{Fore.YELLOW}Pausing for 2 seconds to respect rate limit{Style.RESET_ALL}")
                time.sleep(2)
                
                # Make the request
                response = requests.get(url, headers=self.headers, params=params)
                
                # Successful response
                if response.status_code == 200:
                    print(f"{Fore.GREEN}SUCCESS: {context} completed successfully{Style.RESET_ALL}")
                    return response.json()
                
                # Rate limit or service issues
                if response.status_code in (429, 503, 504):
                    print(f"{Fore.RED}FAILURE: Rate limit or service unavailable (Status {response.status_code}) for {readable_context}. Retrying...{Style.RESET_ALL}")
                    continue
                
                # Non-retriable error
                print(f"{Fore.RED}FAILURE: HTTP Error {response.status_code} for {readable_context}: {response.text}{Style.RESET_ALL}")
                return None
            
            except requests.exceptions.RequestException as e:
                print(f"{Fore.RED}FAILURE: Network error on attempt {attempt + 1} for {readable_context}: {e}{Style.RESET_ALL}")
                
                # If it's the last attempt, return None
                if attempt == max_retries - 1:
                    print(f"{Fore.RED}FINAL FAILURE: All attempts failed for {readable_context}{Style.RESET_ALL}")
                    return None
        
        # Fallback return if loop completes without returning
        print(f"{Fore.RED}FINAL FAILURE: Unexpected termination for {readable_context}{Style.RESET_ALL}")
        return None

    def search_artist_by_id(self, artist_id: str) -> Optional[Dict]:
        """
        Search for an artist directly by ID.
        
        Args:
            artist_id (str): MusicBrainz ID of the artist
            
        Returns:
            Optional[Dict]: Artist information or None if not found
        """
        try:
            result = requests.get(
                f"{self.base_url}artist/{artist_id}", 
                headers=self.headers, 
                params={'fmt': 'json'}
            )
            
            if result.status_code == 200:
                return result.json()
            
            return None
        except Exception:
            return None

    def fetch_artists_by_genres(self, genres: List[str], limit: int = 50) -> List[Dict]:
            """
            Fetch artists matching specified genre families.
            
            Args:
                genres (List[str]): List of genre families to search
                limit (int): Maximum number of artists to return
            
            Returns:
                List[Dict]: List of artist dictionaries
            """
            # Sanity check for input
            if not genres:
                return []
            
            # Use the first genre for searching
            genre = genres[0]
            
            # Search artists by genre
            genre_search_result = self._make_api_request(
                f"{self.base_url}artist", 
                {
                    'query': f'tag:"{genre}"',
                    'limit': limit,
                    'fmt': 'json'
                },
                f"Searching for genre {genre}"
            )
            
            # Return artists or empty list
            if genre_search_result and genre_search_result.get('artists'):
                # Deduplicate while preserving order
                seen_ids = set()
                unique_artists = []
                for artist in genre_search_result['artists']:
                    artist_id = artist.get('id')
                    if artist_id and artist_id not in seen_ids:
                        seen_ids.add(artist_id)
                        unique_artists.append(artist)
                
                return unique_artists[:limit]
            
            return []

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
            f"Searching for artist '{artist_name}'"  # Use artist name instead of UUID
        )
        
        if result and result.get('artists') and len(result['artists']) > 0:
            return result['artists'][0]
        else:
            if result:  # Request succeeded but no artists found
                print(f"{Fore.YELLOW}No artist found for '{artist_name}'{Style.RESET_ALL}")
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
            f"Fetching artist relations for {artist_id}"
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
            f"Fetching genres for {artist_id}"
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
            f"Searching for genre {genres[0]}"
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
            f"Fetching artist name for {artist_id}"
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
            f"Searching for similar names"
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
            f"Getting releases for {artist_id}"
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
            f"Requesting genres for artist"  # Remove the UUID
        )
        
        return [genre['name'] for genre in result.get('genres', [])] if result else []