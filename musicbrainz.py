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
    
    def __init__(self, user_email: str = "your email"):
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
        # Track the time of the last API request to ensure rate limiting
        self.last_request_time = 0

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
                elif 'artist' in params:
                    # For bulk lookup cases
                    readable_context = f"{len(params['artist'].split(','))} artists"
                
                # Log attempt start
                print(f"{Fore.YELLOW}Attempt {attempt + 1} of {max_retries} for {readable_context}")
                print(f"Request URL: {url}")
                # Prevent potential credential exposure in full params logging
                sanitized_params = params.copy()
                if 'artist' in sanitized_params:
                    sanitized_params['artist'] = f"[{len(sanitized_params['artist'].split(','))} artist IDs]"
                print(f"Request Params: {sanitized_params}{Style.RESET_ALL}")
                
                # Ensure rate limiting - respect 2 seconds between API calls
                current_time = time.time()
                time_since_last_request = current_time - self.last_request_time
                
                if time_since_last_request < BASE_REQUEST_DELAY:
                    # Only sleep for the remaining time needed to respect the 2-second limit
                    sleep_time = BASE_REQUEST_DELAY - time_since_last_request
                    print(f"{Fore.YELLOW}Pausing for {sleep_time:.2f} seconds to respect rate limit{Style.RESET_ALL}")
                    time.sleep(sleep_time)
                
                # Make the request
                response = requests.get(url, headers=self.headers, params=params)
                
                # Update the last request time
                self.last_request_time = time.time()
                
                # Successful response
                if response.status_code == 200:
                    print(f"{Fore.GREEN}SUCCESS: {context} completed successfully{Style.RESET_ALL}")
                    return response.json()
                
                # Rate limit or service issues
                if response.status_code in (429, 503, 504):
                    print(f"{Fore.RED}FAILURE: Rate limit or service unavailable (Status {response.status_code}) for {readable_context}. Retrying...{Style.RESET_ALL}")
                    continue
                
                # Non-retriable error - add more detailed logging
                print(f"{Fore.RED}FAILURE: HTTP Error {response.status_code} for {readable_context}: {response.text}{Style.RESET_ALL}")
                
                # Additional debug logging for 400 errors
                if response.status_code == 400:
                    print(f"{Fore.RED}Detailed 400 Error Investigation:{Style.RESET_ALL}")
                    print(f"Request URL: {url}")
                    print(f"Request Headers: {self.headers}")
                    print(f"Request Params (raw): {params}")
                    print(f"Response Body: {response.text}")
                
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

    def get_compilation_recommendations(self, album_names: List[str]) -> Dict[str, List[str]]:
        """
        Generate recommendations from a list of compilation album names.
        
        Args:
            album_names (List[str]): List of album names to process
            
        Returns:
            Dict[str, List[str]]: Dictionary mapping artists to recommendations
        """
        recommendations = {}
        
        for album_name in album_names:
            print(f"{Fore.CYAN}Processing compilation album: {album_name}{Style.RESET_ALL}")
            
            # Get artist information for the album
            artist_info = self.process_various_artists_album(album_name)
            
            # Store recommendations
            for artist in artist_info:
                artist_name = artist['name']
                similar_artists = artist['similar_artists']
                
                if similar_artists:
                    recommendations[artist_name] = similar_artists
                    print(f"{Fore.GREEN}Added {len(similar_artists)} recommendations for '{artist_name}'{Style.RESET_ALL}")
        
        return recommendations

    def process_various_artists_album(self, album_name: str) -> List[Dict]:
        """
        Process a Various Artists album to get artists and their recommendations.
        Finds all artists on the album and generates recommendations for each.
        
        Args:
            album_name (str): Name of the album to look up
            
        Returns:
            List[Dict]: List of artist information dictionaries with recommendations
        """
        # Get all artists on the album
        album_artists = self.get_album_artists(album_name)
        
        if not album_artists:
            print(f"{Fore.YELLOW}No artists found for album '{album_name}'{Style.RESET_ALL}")
            return []
        
        print(f"{Fore.GREEN}Processing {len(album_artists)} artists from album '{album_name}'{Style.RESET_ALL}")
        
        # Store artist information with recommendations
        artist_info = []
        
        # Process each artist
        for artist_name in album_artists:
            try:
                # Search for artist
                print(f"{Fore.CYAN}Looking up artist '{artist_name}' from compilation{Style.RESET_ALL}")
                artist_data = self.search_artist(artist_name)
                
                if not artist_data:
                    print(f"{Fore.YELLOW}Could not find artist '{artist_name}' on MusicBrainz{Style.RESET_ALL}")
                    continue
                
                # Respect API rate limits
                time.sleep(2)
                
                # Get similar artists
                similar_artists = self.get_similar_artists(artist_data['id'], limit=10)
                
                # Store the information
                artist_info.append({
                    'name': artist_name,
                    'id': artist_data['id'],
                    'similar_artists': [a.get('name', '') for a in similar_artists if a]
                })
                
                print(f"{Fore.GREEN}Found {len(similar_artists)} similar artists for '{artist_name}'{Style.RESET_ALL}")
                
            except Exception as e:
                print(f"{Fore.RED}Error processing artist '{artist_name}': {e}{Style.RESET_ALL}")
                
            # Respect API rate limits
            time.sleep(2)
        
        return artist_info

    def get_album_artists(self, album_name: str, artist_name: str = None) -> List[str]:
        """
        Look up artists on an album by album name using MusicBrainz.
        Particularly useful for Various Artists compilations.
        
        Args:
            album_name (str): Name of the album to search for
            artist_name (str, optional): Artist name to refine search
            
        Returns:
            List[str]: List of artist names found on the album
        """
        print(f"{Fore.CYAN}Looking up album '{album_name}' in MusicBrainz{Style.RESET_ALL}")
        
        # Sanitize inputs
        album_name = album_name.strip()
        if artist_name:
            artist_name = artist_name.strip()
        
        # Build search query
        if artist_name and artist_name.lower() not in ('various artists', 'various', 'va', 'v.a.'):
            # If an artist was provided and it's not Various Artists
            query = f'release:"{album_name}" AND artist:"{artist_name}"'
        else:
            # For Various Artists or unknown artist
            if artist_name and artist_name.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                query = f'artist:"{artist_name}" AND release:"{album_name}"' 
            else:
                query = f'artist:"Various Artists" AND release:"{album_name}"'
        
        params = {
            'query': query,
            'limit': 5,  # Look at top 5 matches
            'fmt': 'json'
        }
        
        # Search for the album
        result = self._make_api_request(
            f"{self.base_url}release",
            params,
            f"Searching for album '{album_name}'"
        )
        
        if not result or 'releases' not in result or not result['releases']:
            print(f"{Fore.YELLOW}No album found for '{album_name}'{Style.RESET_ALL}")
            return []
        
        # Get the first matching release ID
        release_id = result['releases'][0]['id']
        
        # Fetch detailed release information including all artists
        detailed_params = {
            'inc': 'recordings+artist-credits',  # Include recordings and artist credits
            'fmt': 'json'
        }
        
        detailed_result = self._make_api_request(
            f"{self.base_url}release/{release_id}",
            detailed_params,
            f"Getting detailed info for album '{album_name}'"
        )
        
        if not detailed_result or 'media' not in detailed_result:
            print(f"{Fore.YELLOW}No detailed info found for album '{album_name}'{Style.RESET_ALL}")
            return []
        
        # Extract unique artists from all tracks
        artists = set()
        
        # Process each medium (CD, vinyl side, etc.)
        for medium in detailed_result['media']:
            if 'tracks' not in medium:
                continue
                
            # Process each track in the medium
            for track in medium['tracks']:
                if 'artist-credit' not in track:
                    continue
                    
                # Extract artist names from credits
                for credit in track['artist-credit']:
                    if isinstance(credit, dict) and 'artist' in credit and 'name' in credit['artist']:
                        artist_name = credit['artist']['name']
                        # Filter out Various Artists
                        if artist_name.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                            artists.add(artist_name)
        
        # Convert set to list
        artist_list = list(artists)
        
        if artist_list:
            print(f"{Fore.GREEN}Found {len(artist_list)} artists on album '{album_name}': {', '.join(artist_list[:5])}{Style.RESET_ALL}")
            if len(artist_list) > 5:
                print(f"{Fore.GREEN}...and {len(artist_list) - 5} more{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}No artists found for album '{album_name}'{Style.RESET_ALL}")
            
        return artist_list

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