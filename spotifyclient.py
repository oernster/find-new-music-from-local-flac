"""
Spotify Client module for creating playlists based on artist recommendations.
"""

import json
import time
import sys
import os
import re
import socket
import logging
import io
import random
import traceback
import backoff
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from spotipy import SpotifyOAuth, Spotify
from spotipy.exceptions import SpotifyException
from colorama import init, Fore, Style

from musicbrainz import MusicBrainzAPI, normalize_artist_name


# Fix console encoding issues on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Initialize Colorama
init(autoreset=True)


class CustomLogFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages."""
    
    def format(self, record):
        """Format log messages with colors."""
        levelname = record.levelname
        message = record.getMessage()
        
        if levelname == 'INFO':
            return f"{Fore.CYAN}{message}{Style.RESET_ALL}"
        elif levelname == 'WARNING':
            return f"{Fore.YELLOW}WARNING: {Fore.RED}{message}{Style.RESET_ALL}"
        elif levelname == 'ERROR':
            if "Failed to resolve 'api.spotify.com'" in message:
                # Mark DNS errors for special handling
                return f"{Fore.YELLOW}ERROR: {Fore.RED}{message}{Style.RESET_ALL} [DNS_ERROR]"
            return f"{Fore.YELLOW}ERROR: {Fore.RED}{message}{Style.RESET_ALL}"
        else:
            return message


# Set up logging
def setup_logging():
    """Configure logging with custom formatter."""
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomLogFormatter())
    
    # Configure root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)


# Define backoff handler
def backoff_hdlr(details):
    """Log information when backing off."""
    logging.warning(
        f"Backing off {details['wait']:0.1f} seconds after {details['tries']} tries "
        f"calling {details['target'].__name__}")


def dns_resolve_backoff(exception):
    """Return True if this is a DNS resolution error."""
    if isinstance(exception, socket.gaierror):
        return True
    if isinstance(exception, Exception) and "getaddrinfo failed" in str(exception):
        return True
    return False


class SpotifyPlaylistManager:
    """Manager for creating Spotify playlists."""
    
    request_delay = 1.2  # Minimum delay between consecutive Spotify API requests
    musicbrainz_delay = 2.0  # Minimum delay between consecutive MusicBrainz API requests

    def __init__(self):
        """Initialize the Spotify Playlist Manager."""
        self.sp = self.create_spotify_client()
        self.mb = MusicBrainzAPI()  # Initialize MusicBrainz API client
        self.last_mb_request_time = 0  # Track time of last MusicBrainz API request
        self.artist_genre_cache = {}  # Cache to store artist genre mappings
        self.total_keys = 0
        self.processed_keys = 0
        self.total_to_process = 0
        self.processed_count = 0
        logging.info("Spotify Authentication Successful!")

    @backoff.on_exception(
        backoff.expo, 
        (socket.gaierror, Exception),
        max_tries=5,
        giveup=lambda e: not dns_resolve_backoff(e),
        on_backoff=backoff_hdlr
    )
    def create_spotify_client(self) -> Spotify:
        """
        Create and authenticate the Spotify client.
        
        Returns:
            Spotify: Authenticated Spotify client
        """
        try:
            # Use comprehensive scopes to ensure we have all needed permissions
            # In the create_spotify_client method, update the scopes list:
            scopes = [
                "playlist-modify-public",
                "playlist-modify-private", 
                "user-library-read",
                "user-read-email",
                "user-read-private",
                "user-top-read"
            ]
            
            auth_manager = SpotifyOAuth(
                client_id="your client id",
                client_secret="your client secret",
                redirect_uri="http://127.0.0.1:8888/callback",
                scope=" ".join(scopes),
                cache_path=".spotify_token_cache"  # Cache token to avoid repeated auth
            )
            
            # Test the connection and token
            client = Spotify(auth_manager=auth_manager)
            
            # Verify token works by making a simple API call
            user = client.current_user()
            logging.info(f"Successfully authenticated as: {user.get('display_name', user.get('id', 'Unknown'))}")
            
            # Check if we have the correct scopes
            token_info = auth_manager.get_cached_token()
            if token_info:
                logging.info(f"Token scopes: {token_info.get('scope', 'Unknown')}")
                
            return client
        except socket.gaierror as e:
            logging.error(f"DNS Resolution Failed: {e}")
            raise
        except Exception as e:
            if "getaddrinfo failed" in str(e):
                logging.error(f"Failed to resolve 'api.spotify.com': {e}")
                raise
            logging.error(f"Spotify Authentication Failed: {e}")
            raise

    def select_json_file(self) -> str:
        """
        Get recommendations file path from environment variable or use the file dialog.
        
        Returns:
            str: Selected file path or empty string if canceled
        """
        # Check if file path is provided in environment variable
        env_file_path = os.environ.get("RECOMMENDATIONS_FILE")
        if env_file_path and os.path.exists(env_file_path):
            logging.info(f"Using recommendations file from environment variable: {env_file_path}")
            return env_file_path
        
        # Otherwise, use the file dialog (fallback)
        logging.info("Please select the source JSON file.")
        root = Tk()
        root.withdraw()
        file_path = askopenfilename(filetypes=[("JSON files", "*.json")])
        root.destroy()
        return file_path

    def normalize_genres(self, genres: List[str]) -> List[str]:
        """
        Normalize genre names for consistency.
        
        Args:
            genres (List[str]): List of genre names to normalize
            
        Returns:
            List[str]: List of normalized genre names
        """
        if not genres:
            return []
        
        # Clean and normalize genres
        normalized = []
        
        # Define substitutions for common genre variations
        substitutions = {
            "r&b": "R&B",
            "rnb": "R&B",
            "rhythm and blues": "R&B",
            "hip hop": "Hip Hop",
            "hip-hop": "Hip Hop",
            "hiphop": "Hip Hop",
            "rock n roll": "Rock & Roll",
            "rock and roll": "Rock & Roll",
            "drum n bass": "Drum & Bass",
            "drum and bass": "Drum & Bass",
            "dnb": "Drum & Bass",
            "edm": "Electronic",
            "electronica": "Electronic",
            # Add more substitutions as needed
        }
        
        # Known meaningless or problematic tags to filter out
        filter_out = [
            'seen live', 'favourite', 'favorite', 'spotify', 'unknown',
            'other', 'others', 'misc', 'miscellaneous', 'various', 'test',
            'check out', 'check this out', 'good', 'great', 'awesome',
            'cool', 'amazing', 'file fix'
        ]
        
        for g in genres:
            if not g or not g.strip():
                continue
                
            # Skip meaningless tags
            if g.lower() in filter_out:
                continue
                
            # Clean up the genre name
            genre_name = g.strip()
            
            # Apply substitutions
            genre_lower = genre_name.lower()
            for old, new in substitutions.items():
                if genre_lower == old:
                    genre_name = new
                    break
                    
            # Title case each word for consistent formatting
            words = genre_name.split()
            title_cased = []
            
            for word in words:
                # Skip title casing for abbreviations and special cases
                if word.lower() in ['&', 'and', 'n', 'of', 'the', 'in', 'at', 'on', 'with']:
                    title_cased.append(word.lower())
                elif word.upper() in ['DJ', 'MC', 'UK', 'US', 'EDM', 'R&B', 'D&B']:
                    title_cased.append(word.upper())
                else:
                    title_cased.append(word.capitalize())
            
            formatted_genre = ' '.join(title_cased)
            
            # Only add if it's not already in the list
            if formatted_genre not in normalized:
                normalized.append(formatted_genre)
        
        # Move more general genres to the front
        # This ensures primary genres are selected correctly
        priority_genres = [
            'Rock', 'Pop', 'Hip Hop', 'Electronic', 'Jazz', 'Classical',
            'R&B', 'Folk', 'Country', 'Metal', 'Blues', 'Soul', 'Funk'
        ]
        
        for priority in reversed(priority_genres):
            if priority in normalized:
                normalized.remove(priority)
                normalized.insert(0, priority)
        
        return normalized

    @backoff.on_exception(
        backoff.expo, 
        (socket.gaierror, SpotifyException),
        max_tries=3,
        on_backoff=backoff_hdlr
    )
    def get_spotify_artist_genres(self, artist_name: str) -> List[str]:
        """
        Fallback method to get artist genres from Spotify when MusicBrainz doesn't have data.
        
        Args:
            artist_name (str): Name of the artist
            
        Returns:
            List[str]: List of genre names from Spotify or empty list if not found
        """
        try:
            # Search for the artist on Spotify
            results = self.retry_on_rate_limit(
                self.sp.search, 
                q=f'artist:"{artist_name}"', 
                type='artist', 
                limit=3
            )
            
            if not results or 'artists' not in results or not results['artists']['items']:
                return []
            
            # Get the top match
            artist = results['artists']['items'][0]
            
            # Ensure it's a reasonably close match
            if artist['name'].lower() != artist_name.lower() and artist_name.lower() not in artist['name'].lower():
                # Check if any words match
                artist_words = set(artist_name.lower().split())
                result_words = set(artist['name'].lower().split())
                
                # If less than half the words match, it's probably not the right artist
                if len(artist_words.intersection(result_words)) < len(artist_words) / 2:
                    return []
            
            # Get the artist's genres
            genres = artist.get('genres', [])
            
            # If we found genres, make sure they're all lowercase for consistency
            return [g for g in genres if g]
            
        except Exception as e:
            logging.error(f"Error getting Spotify genres for '{artist_name}': {e}")
            return []

    def batch_get_artist_genres(self, artists: List[str], batch_size: int = 25) -> Dict[str, Tuple[str, List[str]]]:
        """
        Comprehensively retrieve genres for a batch of artists using multiple strategies.
        
        Args:
            artists (List[str]): List of artist names to get genres for
            batch_size (int): Number of artists to process in each batch
        
        Returns:
            Dict[str, Tuple[str, List[str]]]: Dictionary mapping artist names to (primary_genre, genre_list)
        """
        # Results dictionary to store genre information
        results = {}
        
        # First, filter out cached and duplicate artists
        unique_artists = []
        for artist in artists:
            normalized_name = artist.lower().strip()
            
            # Check cache first
            if normalized_name in self.artist_genre_cache:
                results[artist] = self.artist_genre_cache[normalized_name]
            elif normalized_name not in [u.lower().strip() for u in unique_artists]:
                unique_artists.append(artist)
        
        # If no new artists to look up, return cached results
        if not unique_artists:
            return results
        
        # Process artists in batches
        for i in range(0, len(unique_artists), batch_size):
            batch = unique_artists[i:i+batch_size]
            logging.info(f"Processing batch of {len(batch)} artists")
            
            try:
                # Batch search artists to get their MusicBrainz IDs first
                batch_artist_ids = {}
                for artist_name in batch:
                    try:
                        # Search for the artist to get the ID
                        artist_info = self.mb.search_artist(artist_name)
                        if artist_info:
                            batch_artist_ids[artist_name] = artist_info['id']
                        else:
                            logging.warning(f"No MusicBrainz ID found for artist: {artist_name}")
                    except Exception as e:
                        logging.error(f"Error searching for artist {artist_name}: {e}")
                
                # If no artists found, skip this batch
                if not batch_artist_ids:
                    logging.warning("No artists found in this batch")
                    continue
                
                # Process each artist individually for maximum robustness
                for artist_name, artist_id in batch_artist_ids.items():
                    try:
                        # Detailed genre lookup for each artist
                        genre_params = {
                            'inc': 'genres',
                            'fmt': 'json'
                        }
                        
                        # First, try MusicBrainz direct artist lookup
                        artist_result = self.mb._make_api_request(
                            f"{self.mb.base_url}artist/{artist_id}", 
                            genre_params, 
                            f"Detailed genre lookup for {artist_name}"
                        )
                        
                        # Extract genres from MusicBrainz
                        artist_genres = []
                        if artist_result and 'genres' in artist_result:
                            artist_genres = [genre['name'] for genre in artist_result['genres']]
                            logging.info(f"MusicBrainz genres for {artist_name}: {artist_genres}")
                        
                        # If no genres from MusicBrainz, try Spotify
                        if not artist_genres:
                            logging.info(f"No MusicBrainz genres for {artist_name}, trying Spotify")
                            artist_genres = self.get_spotify_artist_genres(artist_name)
                            logging.info(f"Spotify genres for {artist_name}: {artist_genres}")
                        
                        # Normalize and process genres
                        if artist_genres:
                            cleaned_genres = self.normalize_genres(artist_genres)
                            primary_genre = cleaned_genres[0] if cleaned_genres else "Miscellaneous"
                            
                            # Cache and store results
                            genre_result = (primary_genre, cleaned_genres)
                            results[artist_name] = genre_result
                            self.artist_genre_cache[artist_name.lower().strip()] = genre_result
                            
                            logging.info(f"Processed {artist_name}: Primary Genre = {primary_genre}, All Genres = {cleaned_genres}")
                        else:
                            # Default to Miscellaneous if no genres found
                            results[artist_name] = ("Miscellaneous", [])
                            self.artist_genre_cache[artist_name.lower().strip()] = ("Miscellaneous", [])
                            logging.warning(f"No genres found for {artist_name}")
                    
                    except Exception as e:
                        # Comprehensive error handling for individual artist
                        logging.error(f"Complete error processing genres for {artist_name}: {e}")
                        logging.error(traceback.format_exc())
                        
                        # Fallback to Miscellaneous on complete failure
                        results[artist_name] = ("Miscellaneous", [])
                        self.artist_genre_cache[artist_name.lower().strip()] = ("Miscellaneous", [])
                
                # Pause to respect rate limits
                time.sleep(self.musicbrainz_delay)
            
            except Exception as e:
                # Catch any unexpected batch-level errors
                logging.error(f"Batch genre lookup error: {e}")
                logging.error(traceback.format_exc())
        
        # Ensure we return results for all original artists
        final_results = {}
        for original_artist in artists:
            final_results[original_artist] = results.get(
                original_artist, 
                self.artist_genre_cache.get(
                    original_artist.lower().strip(), 
                    ("Miscellaneous", [])
                )
            )
        
        # Log final results summary
        logging.info("Genre Lookup Summary:")
        genre_distribution = {}
        for artist, (primary_genre, _) in final_results.items():
            genre_distribution[primary_genre] = genre_distribution.get(primary_genre, 0) + 1
        
        for genre, count in sorted(genre_distribution.items(), key=lambda x: x[1], reverse=True):
            logging.info(f"  {genre}: {count} artists")
        
        return final_results

    def get_artist_genre(self, artist_name: str) -> Tuple[str, List[str]]:
        """
        Wrapper for batch genre lookup that works with single artist.
        
        Args:
            artist_name (str): Name of the artist
            
        Returns:
            Tuple[str, List[str]]: (Primary genre, All genres)
        """
        results = self.batch_get_artist_genres([artist_name])
        return results.get(artist_name, ("Miscellaneous", []))
    
    def calculate_genre_similarity(self, genre1: str, genre2: str) -> float:
        """
        Calculate similarity between two genres for determining if they should be merged.
        
        Args:
            genre1 (str): First genre
            genre2 (str): Second genre
            
        Returns:
            float: Similarity score (0.0 to 1.0)
        """
        # Convert to lowercase for comparison
        g1 = genre1.lower()
        g2 = genre2.lower()
        
        # Exact match
        if g1 == g2:
            return 1.0
        
        # Check if one is a subset of the other
        if g1 in g2 or g2 in g1:
            return 0.8
        
        # Break into words for more detailed comparison
        words1 = set(g1.split())
        words2 = set(g2.split())
        
        # Check for common words
        common_words = words1.intersection(words2)
        
        # If they share words, calculate similarity based on word overlap
        if common_words:
            # Calculate Jaccard similarity: intersection / union
            similarity = len(common_words) / len(words1.union(words2))
            return similarity
        
        # If no direct word overlap, check for related genre categories
        related_categories = {
            'rock': ['metal', 'alternative', 'punk', 'indie', 'grunge'],
            'electronic': ['techno', 'house', 'trance', 'edm', 'dance', 'ambient'],
            'pop': ['dance-pop', 'synth-pop', 'electropop', 'europop'],
            'hip hop': ['rap', 'trap', 'urban'],
            'jazz': ['blues', 'swing', 'bebop', 'fusion'],
            'classical': ['orchestral', 'chamber', 'baroque', 'romantic'],
            'folk': ['americana', 'country', 'bluegrass', 'singer-songwriter'],
            'r&b': ['soul', 'funk'],
            'world': ['latin', 'reggae', 'afrobeat', 'traditional'],
        }
        
        # Check if the genres belong to the same category
        for category, related in related_categories.items():
            # Check if both genres are in the same category or one is the category itself
            g1_in_category = g1 == category or any(term in g1 for term in related)
            g2_in_category = g2 == category or any(term in g2 for term in related)
            
            if g1_in_category and g2_in_category:
                # They're related but not direct matches
                return 0.5
        
        # No significant relation
        return 0.0

    def are_genres_distinct(self, genre1: str, genre2: str) -> bool:
        """
        Determine if two genres are distinct enough to justify separate playlists.
        
        Args:
            genre1 (str): First genre
            genre2 (str): Second genre
            
        Returns:
            bool: True if the genres are distinct, False if they're similar
        """
        # Calculate similarity
        similarity = self.calculate_genre_similarity(genre1, genre2)
        
        # Genres are distinct if their similarity is below threshold
        return similarity < 0.6  # Adjust threshold as needed
    
    def read_artist_genres(self, filename: str) -> defaultdict:
        """
        Read artists from JSON file and organize by genre with improved processing.
        - Processes both source artists and their recommendations
        - Better handles large artist collections
        - Improves genre assignment
        
        Args:
            filename (str): Path to the JSON file
            
        Returns:
            defaultdict: Dictionary mapping genres to lists of artists
        """
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                data = json.load(file)
            
            # Dictionary to map genres to artists
            genre_artists = defaultdict(list)
            
            # Collect all unique artists to process (both keys and values)
            all_artists = set()
            source_artists = set(data.keys())
            
            # Add all source artists
            all_artists.update(source_artists)
            
            # Add all recommended artists
            for key_artist, inspired_artists in data.items():
                # Add EVERY recommended artist, not just the default 10
                all_artists.update(inspired_artists)
            
            # Remove duplicates and ensure we have a list
            unique_artists = sorted(list(all_artists))
            
            # Store total count for progress tracking
            self.total_keys = len(unique_artists)
            self.processed_keys = 0
            
            # Log total artists for progress tracking
            logging.info(f"JSON file contains {self.total_keys} total unique artists to process")
            
            # Process in smaller batches for better progress updates
            batch_size = 10  # Increased batch size for faster processing
            for i in range(0, len(unique_artists), batch_size):
                batch = unique_artists[i:i+batch_size]
                
                # Get genres for entire batch at once
                batch_genres = self.batch_get_artist_genres(batch)
                
                for artist in batch:
                    # Get genre for each artist from batch result
                    primary_genre, all_genres = batch_genres.get(artist, self.get_artist_genre(artist))
                    
                    # Skip adding if we couldn't determine a genre
                    if primary_genre == "Miscellaneous" and not all_genres:
                        # Try one more time with direct Spotify lookup as fallback
                        spotify_genres = self.get_spotify_artist_genres(artist)
                        if spotify_genres:
                            cleaned_genres = self.normalize_genres(spotify_genres)
                            if cleaned_genres:
                                primary_genre = cleaned_genres[0]
                                all_genres = cleaned_genres
                    
                    # Add the artist to its primary genre
                    if artist not in genre_artists[primary_genre]:
                        genre_artists[primary_genre].append(artist)
                    
                    # Add to ALL secondary genres to maximize playlist generation
                    if len(all_genres) > 1:
                        for secondary_genre in all_genres[1:]:
                            if secondary_genre != primary_genre:
                                if artist not in genre_artists[secondary_genre]:
                                    genre_artists[secondary_genre].append(artist)
                    
                    # Update processed count and log progress
                    self.processed_keys += 1
                    progress_percent = (self.processed_keys / self.total_keys) * 100
                    if self.processed_keys % 10 == 0 or self.processed_keys == self.total_keys:
                        logging.info(f"Progress: {progress_percent:.1f}% ({self.processed_keys}/{self.total_keys} artists)")
            
            # Instead of removing small categories, keep them for more playlists
            # Only merge categories with fewer than 3 artists
            categories_to_merge = []
            main_categories = {}
            
            # First pass: identify very small categories to potentially merge
            for genre, artists in list(genre_artists.items()):
                if len(artists) < 3:  # Only merge extremely small categories
                    categories_to_merge.append(genre)
                elif genre != "Miscellaneous" and len(artists) >= 5:  # Significant categories
                    main_categories[genre] = len(artists)
            
            # Try to merge tiny categories
            if categories_to_merge and main_categories:
                logging.info(f"Attempting to merge {len(categories_to_merge)} very small categories")
                
                for small_genre in categories_to_merge:
                    if small_genre not in genre_artists:
                        continue
                    
                    small_artists = genre_artists[small_genre]
                    best_match = None
                    max_similarity = 0
                    
                    # Find the most similar major category
                    for main_genre in main_categories:
                        similarity = self.calculate_genre_similarity(small_genre, main_genre)
                        if similarity > max_similarity:
                            max_similarity = similarity
                            best_match = main_genre
                    
                    # Only merge if we found a good match
                    if best_match and max_similarity > 0.5:  # Higher threshold for similarity
                        logging.info(f"Merging '{small_genre}' into '{best_match}' (similarity: {max_similarity:.2f})")
                        
                        # Add artists from small category to the main one
                        for artist in small_artists:
                            if artist not in genre_artists[best_match]:
                                genre_artists[best_match].append(artist)
                        
                        # Remove the small category
                        del genre_artists[small_genre]
            
            # Log summary of genres and artists
            total_artists_in_genres = sum(len(artists) for artists in genre_artists.values())
            logging.info(f"Found {len(genre_artists)} genres with {total_artists_in_genres} total artist assignments")
            for genre, artists in sorted(genre_artists.items(), key=lambda x: len(x[1]), reverse=True):
                logging.info(f"Genre '{genre}': {len(artists)} artists")
            
            return genre_artists
        except Exception as e:
            logging.error(f"Error reading JSON file: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return defaultdict(list)


    @backoff.on_exception(
        backoff.expo, 
        (socket.gaierror, Exception),
        max_tries=5,
        giveup=lambda e: not dns_resolve_backoff(e),
        on_backoff=backoff_hdlr
    )
    def retry_on_rate_limit(self, func, *args, **kwargs) -> Any:
        """
        Retry a function call with backoff for rate limits.
        
        Args:
            func: Function to call
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Any: Result of the function call or None on failure
        """
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Log API call
                logging.info(f"API Call: {func.__name__}")
                result = func(*args, **kwargs)
                time.sleep(self.request_delay)  # Always pause to respect rate limits
                return result
            except SpotifyException as e:
                if e.http_status == 429:  # Rate limit error
                    retry_after = int(e.headers.get("Retry-After", 5))
                    logging.warning(f"Rate limit hit. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after + 1)  # Add 1 second buffer
                    retry_count += 1
                    continue
                elif e.http_status == 401:
                    logging.error(f"Authentication error (401). Token may have expired.")
                    logging.info("Attempting to refresh token...")
                    # Try refreshing token by recreating the client
                    try:
                        self.sp = self.create_spotify_client()
                        logging.info("Token refreshed successfully")
                        retry_count += 1
                        continue
                    except Exception as refresh_error:
                        logging.error(f"Failed to refresh token: {refresh_error}")
                        break
                else:
                    logging.error(f"Spotify API error: {e} (Status: {e.http_status})")
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count)  # Exponential backoff with cap
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
            except socket.gaierror as e:
                logging.error(f"Network error: {e}")
                retry_count += 1
                wait_time = min(30, 2 ** retry_count)
                logging.warning(f"Network issue, retrying in {wait_time}s ({retry_count}/{max_retries})")
                time.sleep(wait_time)
                continue
            except Exception as e:
                if "getaddrinfo failed" in str(e):
                    logging.error(f"Failed to resolve 'api.spotify.com': {e}")
                    retry_count += 1
                    wait_time = min(30, 2 ** retry_count) 
                    logging.warning(f"DNS issue, retrying in {wait_time}s ({retry_count}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                logging.error(f"General error in {func.__name__}: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = min(30, 2 ** retry_count)
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    break
        
        logging.error(f"Failed after {retry_count} retries")
        return None

    def get_track_genres(self, track: Dict, target_genre: str) -> Tuple[bool, float, List[str]]:
        """
        Get genres for a track and check if it matches the target genre with improved matching.
        Uses a more flexible approach to genre matching to include more tracks.
        
        Args:
            track (Dict): Track data from Spotify API
            target_genre (str): Genre we're looking for
            
        Returns:
            Tuple[bool, float, List[str]]: (Matches target, Match score, All genres)
        """
        all_genres = set()
        target_lower = target_genre.lower()
        
        # Check track artists genres from MusicBrainz
        for artist in track.get('artists', []):
            artist_name = artist.get('name', '')
            if not artist_name:
                continue
                
            # Get cached or new genre info for this artist
            primary_genre_name, artist_genres = self.get_artist_genre(artist_name)
            
            # Add normalized genres to our set
            all_genres.update([g.lower() for g in artist_genres])
            
            # Also add the primary genre from MusicBrainz - this is important
            if primary_genre_name:
                all_genres.add(primary_genre_name.lower())
        
        # Create list of all genres found
        genre_list = list(all_genres)
        
        # Check for key signifier genres that strongly indicate a specific classification
        rock_signifiers = {'rock', 'alternative', 'punk', 'metal', 'grunge', 'indie rock', 
                          'hard rock', 'progressive rock', 'classic rock', 'alternative rock',
                          'industrial rock', 'industrial', 'post-punk', 'new wave', 'garage rock'}
                          
        electronic_signifiers = {'electronic', 'techno', 'house', 'trance', 'edm', 'electronica', 
                               'ambient', 'downtempo', 'idm', 'drum and bass', 'dubstep', 'dance'}
        
        pop_signifiers = {'pop', 'dance pop', 'synth pop', 'indie pop', 'europop', 
                         'electropop', 'dance-pop', 'power pop', 'pop rock'}
                         
        hiphop_signifiers = {'hip hop', 'rap', 'trap', 'urban', 'gangsta', 'old school hip hop',
                            'contemporary hip hop', 'conscious hip hop'}
                             
        jazz_signifiers = {'jazz', 'bebop', 'swing', 'fusion', 'big band', 'smooth jazz', 
                           'contemporary jazz', 'free jazz'}
                             
        classical_signifiers = {'classical', 'orchestra', 'symphony', 'baroque', 'chamber', 
                               'piano', 'composer', 'romantic', 'opera'}
                             
        folk_signifiers = {'folk', 'country', 'americana', 'bluegrass', 'traditional', 
                          'singer-songwriter', 'acoustic', 'celtic'}
        
        # Dictionaries for mapping high-level categories to their signifiers
        category_signifiers = {
            'rock': rock_signifiers,
            'electronic': electronic_signifiers,
            'pop': pop_signifiers,
            'hip hop': hiphop_signifiers,
            'jazz': jazz_signifiers,
            'classical': classical_signifiers,
            'folk': folk_signifiers,
        }
        
        # Direct match case - highest score
        if target_lower in all_genres:
            return (True, 1.0, genre_list)
        
        # Check for part of a compound genre (e.g., "Rock - Classic" matches with "rock" genres)
        target_parts = target_lower.split(' - ')
        primary_target = target_parts[0] if target_parts else target_lower
        
        # Check if any of the track's genres directly contain the primary target
        for genre in all_genres:
            if primary_target in genre.split():
                return (True, 0.9, genre_list)
        
        # Check against category signifiers
        # First, see if our target belongs to a known category
        target_category = None
        for category, signifiers in category_signifiers.items():
            if primary_target == category or primary_target in signifiers:
                target_category = category
                break
        
        # If we found the category our target belongs to
        if target_category:
            # Check if any of the track's genres belong to the same category
            track_genre_matches = all_genres.intersection(category_signifiers[target_category])
            if track_genre_matches:
                match_strength = min(0.85, 0.6 + (len(track_genre_matches) * 0.05))
                return (True, match_strength, genre_list)
        
        # For subgenre matching (if target is like "Rock - Progressive")
        if len(target_parts) > 1 and primary_target in category_signifiers:
            # The target is a specific subgenre like "Rock - Progressive"
            subgenre = target_parts[1].lower()
            
            # Look for tracks with any genres containing both the category and subgenre terms
            for genre in all_genres:
                if primary_target in genre and subgenre in genre:
                    return (True, 0.85, genre_list)
                
            # Match just on the subgenre part with lower confidence
            for genre in all_genres:
                if subgenre in genre:
                    return (True, 0.7, genre_list)
        
        # Check for broader pattern matching - look for target words in genres
        target_words = set(target_lower.split())
        for genre in all_genres:
            genre_words = set(genre.split())
            common_words = target_words.intersection(genre_words)
            if common_words and len(common_words) / len(target_words) >= 0.5:
                match_strength = 0.6 + (len(common_words) / len(target_words) * 0.2)
                return (True, match_strength, genre_list)
        
        # For genre conflict cases (e.g., both rock and electronic elements)
        rock_matches = len(all_genres.intersection(rock_signifiers))
        electronic_matches = len(all_genres.intersection(electronic_signifiers))
        
        if rock_matches > 0 and electronic_matches > 0:
            if rock_matches >= electronic_matches and primary_target == 'rock':
                # This is primarily a rock artist appearing in rock playlist
                return (True, 0.8, genre_list)
            elif rock_matches > electronic_matches and primary_target == 'electronic':
                # This is primarily a rock artist wrongly in electronic playlist
                return (False, 0.2, genre_list)
            elif electronic_matches > rock_matches and primary_target == 'electronic':
                # This is primarily an electronic artist in electronic playlist
                return (True, 0.8, genre_list)
            elif electronic_matches >= rock_matches and primary_target == 'rock':
                # This is primarily an electronic artist wrongly in rock playlist
                return (False, 0.2, genre_list)
        
        # Default case - low match score
        return (False, 0.3, genre_list)

    def get_simplified_track_match(self, artist_tuple: Tuple[str, List[str]], target_genre: str) -> Tuple[bool, float]:
        """
        Improved method to match an artist against a target genre using cached genre info.
        More lenient matching to improve discovery while maintaining genre relevance.
        
        Args:
            artist_tuple (Tuple[str, List[str]]): Tuple containing (artist_name, artist_genres)
            target_genre (str): Target genre to match against
            
        Returns:
            Tuple[bool, float]: (Matches target, Match score)
        """
        _, artist_genres = artist_tuple
        
        # If the artist has no genre info, give it a higher score to include more artists
        if not artist_genres:
            return (True, 0.5)  # More permissive matching for unknown genres
        
        # Convert everything to lowercase for comparison
        artist_genres_lower = [g.lower() for g in artist_genres]
        target_lower = target_genre.lower()
        
        # Extract primary and secondary parts of the target genre
        target_parts = target_lower.split(' - ')
        primary_target = target_parts[0]
        secondary_target = target_parts[1] if len(target_parts) > 1 else None
        
        # Direct match case - highest score
        if target_lower in artist_genres_lower:
            return (True, 1.0)
        
        # Primary genre match - high score
        if primary_target in artist_genres_lower:
            return (True, 0.9)
        
        # Check if any artist genre contains the primary target
        for genre in artist_genres_lower:
            if primary_target in genre.split():
                return (True, 0.85)
        
        # Secondary target match if it exists
        if secondary_target:
            for genre in artist_genres_lower:
                if secondary_target in genre:
                    return (True, 0.8)
        
        # Check for related genres with comprehensive mapping
        related_genres = {
            # Rock family
            'rock': ['alternative', 'indie', 'punk', 'metal', 'hard rock', 'classic rock', 
                    'progressive rock', 'art rock', 'industrial rock', 'industrial', 
                    'alternative rock', 'post-punk', 'grunge', 'new wave', 'garage'],
            
            # Metal family - added as separate category
            'metal': ['heavy metal', 'thrash metal', 'death metal', 'black metal', 'doom metal', 
                     'progressive metal', 'power metal', 'folk metal', 'gothic metal', 'alternative metal'],
            
            # Electronic music family
            'electronic': ['techno', 'house', 'trance', 'edm', 'dance', 'ambient', 'dubstep',
                          'electronica', 'downtempo', 'idm', 'drum and bass', 'electro', 
                          'breakbeat', 'jungle', 'trip hop'],
            
            # Pop music family
            'pop': ['dance pop', 'synth pop', 'indie pop', 'electropop', 'pop rock', 'europop',
                   'power pop', 'chamber pop', 'baroque pop', 'dream pop', 'sophisti-pop'],
            
            # Hip hop family
            'hip hop': ['rap', 'trap', 'gangsta rap', 'conscious hip hop', 'old school hip hop',
                       'alternative hip hop', 'southern hip hop', 'east coast hip hop', 'west coast hip hop'],
            
            # R&B and Soul family
            'r&b': ['soul', 'funk', 'contemporary r&b', 'neo soul', 'rhythm and blues', 'gospel'],
            
            # Jazz family
            'jazz': ['bebop', 'swing', 'fusion', 'blues', 'smooth jazz', 'free jazz', 'modal jazz', 
                   'cool jazz', 'hard bop', 'avant-garde jazz', 'big band'],
            
            # Classical music family
            'classical': ['baroque', 'romantic', 'contemporary classical', 'orchestral', 'chamber music',
                         'opera', 'symphony', 'concerto', 'sonata', 'piano'],
            
            # Folk and Country family
            'folk': ['acoustic', 'singer-songwriter', 'americana', 'country', 'bluegrass',
                   'traditional folk', 'folk rock', 'british folk', 'celtic'],
            
            'country': ['country rock', 'outlaw country', 'country pop', 'alternative country',
                       'traditional country', 'honky tonk', 'americana', 'bluegrass'],
                       
            # World music family
            'world': ['reggae', 'latin', 'afrobeat', 'afro-pop', 'bossa nova', 'salsa', 'samba',
                     'flamenco', 'celtic', 'traditional'],
                     
            # Additional categories for better matching
            'indie': ['indie rock', 'indie pop', 'alternative', 'lo-fi', 'post-rock', 'shoegaze'],
            
            'alternative': ['alternative rock', 'indie', 'post-punk', 'grunge', 'new wave',
                           'college rock', 'experimental rock'],
                           
            'punk': ['hardcore', 'post-punk', 'pop punk', 'skate punk', 'anarcho-punk',
                    'garage punk', 'punk rock', 'oi!'],
                    
            'ambient': ['downtempo', 'chillout', 'drone', 'ambient electronic', 'dark ambient'],
            
            'experimental': ['avant-garde', 'noise', 'industrial', 'experimental rock', 
                           'experimental electronic', 'musique concrète'],
                           
            # Genre refinements for more accurate matching
            # House music variants
            'house': ['deep house', 'tech house', 'progressive house', 'acid house', 'electro house'],
            
            # Trance music variants
            'trance': ['progressive trance', 'uplifting trance', 'psychedelic trance', 'goa trance'],
            
            # Techno music variants
            'techno': ['minimal techno', 'detroit techno', 'hard techno', 'acid techno'],
        }
        
        # Check for related genres
        if primary_target in related_genres:
            related = related_genres[primary_target]
            # Check if any of artist's genres are in the related genres for target
            matches = [g for g in artist_genres_lower if g in related]
            if matches:
                # Score is higher when more related genres match - be more lenient
                match_score = min(0.85, 0.6 + (len(matches) * 0.1))
                return (True, match_score)
        
        # Check if target might be a subgenre
        for category, related in related_genres.items():
            if primary_target in related:
                # Check if the artist has the parent category - be more lenient
                if category in artist_genres_lower:
                    return (True, 0.75)
                
                # Check if artist has other related genres in the same category
                related_matches = [g for g in artist_genres_lower if g in related]
                if related_matches:
                    match_score = min(0.75, 0.6 + (len(related_matches) * 0.05))
                    return (True, match_score)
        
        # Check if any of artist's genres have the target as a substring or vice versa
        partial_matches = []
        for artist_genre in artist_genres_lower:
            # Either target in genre, or genre in target
            if primary_target in artist_genre or any(part in primary_target for part in artist_genre.split()):
                partial_matches.append(artist_genre)
        
        if partial_matches:
            # Use the best score from partial matches - be more lenient
            partial_score = min(0.75, 0.5 + (len(partial_matches) * 0.1))
            return (True, partial_score)
        
        # Check for word-level matches (more fuzzy) - be more lenient
        target_words = set(primary_target.split())
        for genre in artist_genres_lower:
            genre_words = set(genre.split())
            common_words = target_words.intersection(genre_words)
            if common_words:
                # Calculate a score based on the percentage of matching words
                word_match_ratio = len(common_words) / len(target_words)
                if word_match_ratio >= 0.3:  # Lower threshold for matching (was 0.5)
                    word_match_score = 0.5 + (word_match_ratio * 0.3)  # Max 0.8
                    return (True, word_match_score)
        
        # More permissive fallback - return matching with low score instead of non-matching
        return (True, 0.4)  # Return true with a low score to include more artists

    def organise_artist_tracks(self, artist: str, target_genre: str) -> List[Tuple[str, float]]:
        """
        Get genre-appropriate tracks for an artist with improved genre matching.
        Provides more reliable track selection and better genre matching.
        
        Args:
            artist (str): Artist name
            target_genre (str): Target genre for filtering
            
        Returns:
            List[Tuple[str, float]]: List of (track_id, match_score) tuples
        """
        # First, get the genres for this artist from MusicBrainz
        _, artist_genres = self.get_artist_genre(artist)
        artist_genres_lower = [g.lower() for g in artist_genres]
        
        # Check if this is a major artist (has genre information in MusicBrainz)
        is_major_artist = len(artist_genres) > 0
        
        # Perform more specific genre search to get better matches
        search_results = []
        quoted_artist = f'artist:"{artist}"'
        
        # For major artists, use genre to help with search
        if is_major_artist:
            # Extract genre terms from target_genre that might help with search
            target_parts = target_genre.lower().split(' - ')
            primary_genre = target_parts[0]
            secondary_genre = target_parts[1] if len(target_parts) > 1 else None
            
            # Try to find matching genre in artist's known genres first
            matching_genres = []
            
            # Check primary genre matches
            for genre in artist_genres_lower:
                if primary_genre in genre:
                    matching_genres.append(genre)
            
            # If we have a secondary genre specification, check for that too
            if secondary_genre:
                for genre in artist_genres_lower:
                    if secondary_genre in genre:
                        # Prioritize genres that match the secondary term
                        if genre not in matching_genres:
                            matching_genres.append(genre)
            
            # If we have found matching genres, use them in the search
            if matching_genres:
                # Try up to 3 matching genres for search
                for search_genre in matching_genres[:3]:
                    genre_query = f'{quoted_artist} genre:"{search_genre}"'
                    logging.info(f"Searching with specific genre context: {genre_query}")
                    genre_results = self.retry_on_rate_limit(self.sp.search, q=genre_query, type='artist', limit=10)
                    
                    if genre_results and 'artists' in genre_results and genre_results['artists']['items']:
                        search_results = genre_results['artists']['items']
                        logging.info(f"Found {len(search_results)} results using genre-based search")
                        break  # Use the first successful genre search
            
            # If no results with specific genres, try the primary genre
            if not search_results and primary_genre:
                genre_query = f'{quoted_artist} genre:"{primary_genre}"'
                logging.info(f"Searching with primary genre: {genre_query}")
                genre_results = self.retry_on_rate_limit(self.sp.search, q=genre_query, type='artist', limit=10)
                
                if genre_results and 'artists' in genre_results and genre_results['artists']['items']:
                    search_results = genre_results['artists']['items']
                    logging.info(f"Found {len(search_results)} results using primary genre search")
        
        # If still no results, fall back to just the artist name
        if not search_results:
            logging.info(f"Using standard artist search: {quoted_artist}")
            quoted_results = self.retry_on_rate_limit(self.sp.search, q=quoted_artist, type='artist', limit=15)
            search_results = quoted_results.get('artists', {}).get('items', []) if quoted_results else []
        
        # If still no results, try a broader search
        if not search_results:
            broader_query = artist  # Just the artist name without quotes
            logging.info(f"Using broader artist search: {broader_query}")
            broader_results = self.retry_on_rate_limit(self.sp.search, q=broader_query, type='artist', limit=20)
            search_results = broader_results.get('artists', {}).get('items', []) if broader_results else []
        
        if not search_results:
            logging.warning(f"No Spotify artists found for '{artist}'")
            return []
        
        # Find the best match using multiple criteria
        artist_lower = artist.lower()
        best_match = None
        exact_matches = []
        name_contains_matches = []
        fuzzy_matches = []
        
        for result in search_results:
            result_name = result.get('name', '')
            result_lower = result_name.lower()
            popularity = result.get('popularity', 0)
            
            # Exact name match - highest priority
            if result_lower == artist_lower:
                exact_matches.append((result, popularity))
            # Name contains match - medium priority
            elif artist_lower in result_lower or result_lower in artist_lower:
                name_contains_matches.append((result, popularity))
            # Fuzzy name match - lowest priority
            else:
                # Simplistic fuzzy matching - could be improved
                if any(part in result_lower for part in artist_lower.split()):
                    fuzzy_matches.append((result, popularity))
        
        # Select the best match by priority and popularity
        if exact_matches:
            # Prefer exact name matches sorted by popularity
            exact_matches.sort(key=lambda x: x[1], reverse=True)
            best_match = exact_matches[0][0]
            logging.info(f"Using exact name match: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
        elif name_contains_matches:
            # Next prefer contained name matches
            name_contains_matches.sort(key=lambda x: x[1], reverse=True)
            best_match = name_contains_matches[0][0]
            logging.info(f"Using name contains match: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
        elif fuzzy_matches:
            # Last resort fuzzy matches
            fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
            best_match = fuzzy_matches[0][0]
            logging.warning(f"Using fuzzy name match: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
        else:
            # If nothing else, use the most popular result
            search_results.sort(key=lambda x: x.get('popularity', 0), reverse=True)
            best_match = search_results[0]
            logging.warning(f"Using most popular result as fallback: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
        
        # NEW CHECK: Only proceed if the match is reasonably good
        selected_name = best_match['name'].lower()
        if selected_name != artist_lower and not (artist_lower in selected_name or selected_name in artist_lower):
            # Only skip if the names are completely different
            if not any(part in selected_name for part in artist_lower.split()) and not any(part in artist_lower for part in selected_name.split()):
                logging.warning(f"Skipping '{artist}' because Spotify matched name '{best_match['name']}' is too different.")
                return []
        
        artist_id = best_match['id']
        artist_name = best_match['name']
        
        # Get artist's top tracks with increased limit for more choices
        try:
            top_tracks = self.retry_on_rate_limit(self.sp.artist_top_tracks, artist_id)
        except Exception as e:
            logging.error(f"Error getting top tracks for {artist_name}: {e}")
            return []
        
        matching_tracks = []
        all_tracks = []
        
        if top_tracks and 'tracks' in top_tracks:
            for track in top_tracks['tracks']:
                track_id = track['id']
                track_name = track['name']
                
                # MODIFIED: Prioritize tracks where this artist is the primary artist
                primary_artist = track['artists'][0] if track['artists'] else None
                is_primary = primary_artist and primary_artist['id'] == artist_id
                
                # Check match score against target genre
                # First use the simplified track match for speed
                artist_tup = (artist, artist_genres)
                matches, score = self.get_simplified_track_match(artist_tup, target_genre)
                
                # If the artist is not the primary artist, reduce the score
                if not is_primary:
                    score *= 0.8  # 20% penalty for not being primary artist
                
                track_info = (track_id, score)
                
                # Keep all tracks in a separate list
                all_tracks.append(track_info)
                
                # Add matching tracks to our results list
                if matches:
                    matching_tracks.append(track_info)
                    logging.info(f"Found matching track for '{artist_name}': '{track_name}' (Score: {score:.2f})")
                    genre_list = [g.lower() for g in artist_genres]
                    logging.info(f"  - Track genres: {genre_list}")
        
        # If we have matches, great; otherwise we do best-effort top tracks
        if matching_tracks:
            logging.info(f"Found {len(matching_tracks)} genre-matching tracks out of {len(all_tracks)} for '{artist_name}' in genre '{target_genre}'")
        else:
            logging.warning(f"No genre-matching tracks found for '{artist_name}' in genre '{target_genre}'")
            if all_tracks:
                # Take top 5 anyway, but artificially adjust scores
                # Prioritize tracks by both popularity and artist match
                top_5 = sorted(all_tracks, key=lambda x: x[1], reverse=True)[:5]
                
                # Apply a more generous score for these tracks to ensure inclusion
                # but still below direct genre matches
                matching_tracks = [(tid, min(s + 0.15, 0.65)) for tid, s in top_5]
                logging.info(f"Using {len(matching_tracks)} best-effort tracks for '{artist_name}'")
        
        # Sort final results by match score, descending
        matching_tracks.sort(key=lambda x: x[1], reverse=True)
        
        # Return top 5
        return matching_tracks[:5]

    def classify_unmapped_genre(self, genre: str) -> str:
        """
        Intelligently classify a genre that isn't in our mapping by looking for common terms.
        This helps ensure we don't end up with "Other" playlists.
        
        Args:
            genre (str): The genre to classify
            
        Returns:
            str: A more general but meaningful genre category
        """
        # Convert to lowercase for matching
        genre_lower = genre.lower()
        
        # Check for common terms in the genre name
        if any(term in genre_lower for term in ['rock', 'metal', 'punk', 'grunge', 'alternative rock']):
            if 'metal' in genre_lower:
                return "Metal"
            elif 'punk' in genre_lower:
                return "Punk"
            elif 'alternative' in genre_lower:
                return "Rock - Alternative"
            elif 'indie' in genre_lower:
                return "Rock - Indie"
            else:
                return "Rock"
                
        elif any(term in genre_lower for term in ['electronic', 'techno', 'house', 'trance', 'edm', 'dance', 'dubstep', 'drum', 'bass']):
            if 'house' in genre_lower:
                return "Electronic - House"
            elif 'trance' in genre_lower:
                return "Electronic - Trance"
            elif 'techno' in genre_lower:
                return "Electronic - Techno"
            elif 'ambient' in genre_lower:
                return "Electronic - Ambient"
            elif any(term in genre_lower for term in ['drum', 'bass']):
                return "Electronic - Drum & Bass"
            else:
                return "Electronic"
                
        elif any(term in genre_lower for term in ['pop', 'synth-pop', 'synthpop', 'dance-pop', 'europop']):
            if 'synth' in genre_lower:
                return "Pop - Synth"
            elif 'dance' in genre_lower:
                return "Pop - Dance"
            else:
                return "Pop"
                
        elif any(term in genre_lower for term in ['hip hop', 'hip-hop', 'rap', 'urban', 'trap']):
            if 'trap' in genre_lower:
                return "Hip Hop - Trap"
            else:
                return "Hip Hop"
                
        elif any(term in genre_lower for term in ['jazz', 'blues', 'soul', 'funk', 'bebop', 'swing']):
            if 'blues' in genre_lower:
                return "Blues"
            elif 'soul' in genre_lower:
                return "Soul"
            elif 'funk' in genre_lower:
                return "Funk"
            elif any(term in genre_lower for term in ['bebop', 'swing', 'big band']):
                return "Jazz - Traditional"
            else:
                return "Jazz"
                
        elif any(term in genre_lower for term in ['folk', 'country', 'americana', 'bluegrass', 'singer-songwriter']):
            if 'country' in genre_lower:
                return "Country"
            elif 'bluegrass' in genre_lower:
                return "Folk - Bluegrass"
            elif 'singer-songwriter' in genre_lower:
                return "Singer-Songwriter"
            else:
                return "Folk"
                
        elif any(term in genre_lower for term in ['classical', 'orchestra', 'symphony', 'baroque', 'piano', 'composer']):
            if 'baroque' in genre_lower:
                return "Classical - Baroque"
            elif 'piano' in genre_lower:
                return "Classical - Piano"
            elif any(term in genre_lower for term in ['orchestra', 'symphony', 'philharmonic']):
                return "Classical - Orchestral"
            elif 'composer' in genre_lower:
                return "Classical - Composer"
            else:
                return "Classical"
                
        elif any(term in genre_lower for term in ['world', 'latin', 'reggae', 'afro', 'celtic', 'traditional', 'folk']):
            if 'latin' in genre_lower:
                return "Latin"
            elif 'reggae' in genre_lower:
                return "Reggae"
            elif 'celtic' in genre_lower:
                return "World - Celtic"
            elif 'afro' in genre_lower:
                return "World - Afrobeat"
            else:
                return "World"
                
        elif any(term in genre_lower for term in ['indie', 'alternative']):
            if 'indie pop' in genre_lower:
                return "Indie Pop"
            elif 'indie' in genre_lower:
                return "Indie"
            else:
                return "Alternative"
                
        elif any(term in genre_lower for term in ['disco', 'funk', '70s']):
            return "Disco & Funk"
            
        elif any(term in genre_lower for term in ['soundtrack', 'score', 'film', 'movie']):
            return "Soundtrack"
            
        elif any(term in genre_lower for term in ['ambient', 'chill', 'lounge', 'downtempo']):
            return "Ambient & Chillout"
            
        # R&B variations
        elif any(term in genre_lower for term in ['r&b', 'rnb', 'rhythm and blues', 'contemporary r&b']):
            return "R&B"
        
        # If we can't identify it, use the original genre name rather than "Other"
        # This ensures we don't lose any potential playlist
        words = genre_lower.split()
        if len(words) > 1:
            # For multi-word genres, capitalize each word
            return ' '.join(word.capitalize() for word in words)
        else:
            # For single word genres, just capitalize
            return genre.capitalize()

    def generate_playlists_by_genre(self, genre_artists: Dict[str, List[str]]) -> None:
        """
        Generate playlists by genre from artist recommendations.
        - Creates more specific genre playlists to increase total number
        - Ensures better distribution of artists across genre categories
        - Lowers minimum thresholds for playlist creation
        
        Args:
            genre_artists (Dict[str, List[str]]): Dictionary mapping genres to artists
        """
        genre_mapping = {
            # Electronic music family - expanded
            "ambient trance": "Electronic - Trance",
            "alternative dance": "Electronic - Dance",
            "dance": "Electronic - Dance",
            "trance": "Electronic - Trance",
            "progressive trance": "Electronic - Trance",
            "progressive house": "Electronic - House",
            "house": "Electronic - House",
            "techno": "Electronic - Techno",
            "edm": "Electronic - Dance",
            "electronica": "Electronic",
            "electronic": "Electronic",
            "electro house": "Electronic - House",
            "drum and bass": "Electronic - Drum & Bass",
            "dubstep": "Electronic - Bass",
            "ambient": "Electronic - Ambient",
            "idm": "Electronic - IDM",
            "downtempo": "Electronic - Downtempo",
            
            # Rock music family - expanded
            "aor": "Rock - Classic",
            "arena rock": "Rock - Classic",
            "classic rock": "Rock - Classic",
            "hard rock": "Rock - Hard Rock",
            "blues rock": "Rock - Blues Rock",
            "rock": "Rock",
            "rock and roll": "Rock & Roll",
            "alternative rock": "Rock - Alternative",
            "indie rock": "Rock - Indie",
            "pop rock": "Rock - Pop Rock",
            "progressive rock": "Rock - Progressive",
            "psychedelic rock": "Rock - Psychedelic",
            "metal": "Metal",
            "heavy metal": "Metal - Heavy",
            "glam metal": "Metal - Glam",
            "grunge": "Rock - Grunge",
            "punk": "Punk",
            "punk rock": "Punk Rock",
            "post-punk": "Rock - Post-Punk",
            "garage": "Rock - Garage",
            
            # Pop music family - expanded
            "art pop": "Pop - Art",
            "alternative pop": "Pop - Alternative",
            "dance-pop": "Pop - Dance",
            "synth-pop": "Pop - Synth",
            "electropop": "Pop - Electronic",
            "pop": "Pop",
            "contemporary r&b": "R&B - Contemporary",
            "r&b": "R&B",
            "europop": "Pop - European",
            "bubblegum pop": "Pop",
            
            # Folk/Country music family - expanded
            "americana": "Folk & Americana",
            "folk": "Folk",
            "country": "Country",
            "country pop": "Country - Pop",
            "bluegrass": "Folk - Bluegrass",
            "singer-songwriter": "Singer-Songwriter",
            "traditional folk": "Folk - Traditional",
            
            # Jazz and Blues family - expanded
            "blues": "Blues",
            "jazz": "Jazz",
            "bebop": "Jazz - Bebop",
            "fusion": "Jazz - Fusion",
            "smooth jazz": "Jazz - Smooth",
            "swing": "Jazz - Swing",
            "big band": "Jazz - Big Band",
            "soul": "Soul",
            "funk": "Funk",
            "gospel": "Gospel",
            
            # Hip Hop family - expanded
            "hip hop": "Hip Hop",
            "rap": "Hip Hop",
            "trap": "Hip Hop - Trap",
            "urban": "Urban",
            "conscious hip hop": "Hip Hop - Conscious",
            "gangsta rap": "Hip Hop - Gangsta",
            "old school hip hop": "Hip Hop - Old School",
            
            # Classical music family - new
            "classical": "Classical",
            "baroque": "Classical - Baroque",
            "romantic": "Classical - Romantic",
            "symphony": "Classical - Orchestral",
            "opera": "Classical - Opera",
            "chamber music": "Classical - Chamber",
            "contemporary classical": "Classical - Contemporary",
            "orchestral": "Classical - Orchestral",
            "piano": "Classical - Piano",
            
            # World music family - new
            "world": "World",
            "reggae": "Reggae",
            "latin": "Latin",
            "afrobeat": "World - Afrobeat",
            "bossa nova": "Latin - Bossa Nova",
            "flamenco": "World - Flamenco",
            "salsa": "Latin - Salsa",
            "traditional": "World - Traditional",
            "celtic": "World - Celtic",
            
            # Other specific genres that shouldn't be "Other"
            "new wave": "New Wave",
            "disco": "Disco",
            "synthwave": "Synthwave",
            "experimental": "Experimental",
            "indie": "Indie",
            "indie pop": "Indie Pop",
            "alternative": "Alternative",
            "soundtrack": "Soundtrack",
            "instrumental": "Instrumental",
            "lounge": "Lounge",
            "chillout": "Chillout",
            "vocal": "Vocal",
            "composer": "Classical - Composer"
        }
        
        # Create a new dictionary with general genre categories
        general_genre_artists = defaultdict(list)
        
        # Split large genres into subgenres for more playlists
        for specific_genre, artists in genre_artists.items():
            # Convert to lowercase for matching
            specific_genre_lower = specific_genre.lower()
            
            # Look up the general category
            general_genre = genre_mapping.get(specific_genre_lower)
            if not general_genre:
                # If not found in mapping, try to intelligently classify it
                general_genre = self.classify_unmapped_genre(specific_genre)
            
            # Add artists to the general genre
            general_genre_artists[general_genre].extend(artists)
            
            # For larger genres (more than 40 artists), create additional sub-playlists
            if len(artists) > 40:
                # Create a more specific subgenre
                subgenre = f"{general_genre} - Selected"
                # Take top 30 artists (can be sorted by popularity if available)
                general_genre_artists[subgenre] = artists[:30]
                
                # For even larger genres, create multiple sub-playlists
                if len(artists) > 80:
                    subgenre2 = f"{general_genre} - Essentials"
                    general_genre_artists[subgenre2] = artists[30:60]
                    
                if len(artists) > 120:
                    subgenre3 = f"{general_genre} - Discover"
                    general_genre_artists[subgenre3] = artists[60:90]
            
            # Log the mapping
            logging.info(f"Mapped '{specific_genre}' to general category '{general_genre}'")
        
        # Remove duplicates in each general category
        for genre, artists in general_genre_artists.items():
            general_genre_artists[genre] = list(dict.fromkeys(artists))
            logging.info(f"General category '{genre}' has {len(general_genre_artists[genre])} unique artists")
        
        # Now process with the general categories
        all_playlists = defaultdict(list)
        
        # Reset counters for playlist generation phase
        self.total_to_process = sum(len(artists) for artists in general_genre_artists.values())
        self.processed_count = 0
                
        # Process all artists by general genre
        for genre, artists in general_genre_artists.items():
            logging.info(f"Processing artists in genre: {genre}")
            
            # Track all artist tracks separately before merging to allow better randomization
            artist_track_mapping = {}  
            total_tracks_found = 0
            on_genre_tracks = 0
            
            for artist in artists:
                logging.info(f"Organizing tracks for artist: {artist}")
                
                # Get tracks with genre matching - use the general genre
                track_matches = self.organise_artist_tracks(artist, genre)
                
                if track_matches:
                    # Get just the track IDs from matches
                    track_ids = [track_id for track_id, _ in track_matches]
                    total_tracks_found += len(track_ids)
                    
                    # Count tracks with good genre match (score >= 0.7)
                    good_matches = sum(1 for _, score in track_matches if score >= 0.7)
                    on_genre_tracks += good_matches
                    
                    # Store tracks by artist
                    artist_track_mapping[artist] = track_ids
                
                # Update progress
                self.processed_count += 1
                progress_percent = (self.processed_count / self.total_to_process) * 100
                logging.info(f"Progress: {progress_percent:.1f}% ({self.processed_count}/{self.total_to_process} artists)")
            
            # Log genre match stats
            if total_tracks_found > 0:
                match_percent = (on_genre_tracks / total_tracks_found) * 100
                logging.info(f"Genre '{genre}' track statistics:")
                logging.info(f"  - Total tracks: {total_tracks_found}")
                logging.info(f"  - Strong genre matches: {on_genre_tracks} ({match_percent:.1f}%)")
            
            # Lower minimum threshold for playlist creation to 12 tracks
            if total_tracks_found >= 12:
                # Create an intelligently randomized track list
                genre_tracks = self.create_balanced_playlist(artist_track_mapping)
                
                logging.info(f"Created balanced playlist with {len(genre_tracks)} tracks for genre '{genre}'")
                
                # Use genre name for playlist
                playlist_name = f"{genre} Mix"
                
                # For playlists with more than 100 tracks, split into multiple playlists
                if len(genre_tracks) > 100:
                    # Add up to 100 tracks per playlist
                    all_playlists[playlist_name] = genre_tracks[:100]
                    
                    # Handle additional playlists if we have a lot of tracks
                    chunks = [genre_tracks[i:i+100] for i in range(100, len(genre_tracks), 100)]
                    for i, chunk in enumerate(chunks, 1):
                        if len(chunk) >= 12:  # Lowered threshold for additional playlists
                            all_playlists[f"{genre} Mix {i+1}"] = chunk
                else:
                    # For smaller playlists, use all available tracks
                    all_playlists[playlist_name] = genre_tracks
                    
            elif total_tracks_found >= 8:  # Even lower threshold for sampler playlists
                # For smaller collections between 8-11 tracks, create a "Sampler" playlist
                logging.info(f"Creating sampler playlist with {total_tracks_found} tracks for genre '{genre}'")
                
                # Create balanced playlist with what we have
                genre_tracks = self.create_balanced_playlist(artist_track_mapping)
                playlist_name = f"{genre} Sampler"
                all_playlists[playlist_name] = genre_tracks
            else:
                logging.warning(f"Not enough tracks for genre '{genre}' (found {total_tracks_found}, need at least 8)")

        # Debug summary
        logging.info(f"Processed {self.processed_count} artists")
        logging.info(f"Total playlists to create: {len(all_playlists)}")
        for name, tracks in all_playlists.items():
            logging.info(f"Playlist '{name}': {len(tracks)} tracks")

        # Ensure progress shows completion
        logging.info(f"Progress: 100% (Generation phase complete)")
        
        if not all_playlists:
            logging.warning("No tracks were found for any artists")
            return
                
        # Create the playlists in Spotify
        self.create_playlists_in_spotify(all_playlists)

    def create_balanced_playlist(self, artist_track_mapping: Dict[str, List[str]]) -> List[str]:
        """
        Create a balanced playlist to avoid consecutive tracks by the same artist.
        
        Args:
            artist_track_mapping (Dict[str, List[str]]): Dictionary mapping artists to their track IDs
            
        Returns:
            List[str]: A balanced list of track IDs
        """
        # First, get all tracks for initial shuffle
        all_artists = list(artist_track_mapping.keys())
        
        # No need to balance if we have 0 or 1 artist
        if len(all_artists) <= 1:
            all_tracks = []
            for tracks in artist_track_mapping.values():
                all_tracks.extend(tracks)
            random.shuffle(all_tracks)
            return all_tracks
        
        # Shuffle the artists first
        random.shuffle(all_artists)
        
        # Create a queue for each artist's tracks
        artist_queues = {}
        for artist in all_artists:
            tracks = artist_track_mapping[artist].copy()
            random.shuffle(tracks)  # Shuffle each artist's tracks
            artist_queues[artist] = tracks
        
        # Build the balanced playlist by rotating through artists
        balanced_playlist = []
        
        # Continue until all tracks are used
        while any(len(queue) > 0 for queue in artist_queues.values()):
            # Reshuffle artist order for each rotation to further randomize
            random.shuffle(all_artists)
            
            # Add one track from each artist that still has tracks
            for artist in all_artists:
                if artist_queues[artist]:
                    # Add the next track for this artist
                    track = artist_queues[artist].pop(0)
                    balanced_playlist.append(track)
        
        return balanced_playlist

    def create_playlists_in_spotify(self, all_playlists: Dict[str, List[str]]) -> None:
        """
        Create playlists in Spotify with improved naming and organization.
        Ensures a consistent naming scheme and better description.
        
        Args:
            all_playlists (Dict[str, List[str]]): Dictionary mapping playlist names to track IDs
        """
        try:
            # Get user details and log them for debugging
            user_details = self.sp.current_user()
            user_id = user_details['id']
            display_name = user_details.get('display_name', 'Unknown')
            logging.info(f"Creating playlists for Spotify user: {user_id} ({display_name})")
            
            # Log the playlists we're about to create
            logging.info(f"Attempting to create {len(all_playlists)} playlists")
            for playlist_name, tracks in all_playlists.items():
                logging.info(f"  - '{playlist_name}': {len(tracks)} tracks")
            
            # Sort playlists by name for consistent ordering
            sorted_playlists = sorted(all_playlists.items(), key=lambda x: x[0])
            
            # Track playlist creation for reporting
            successful_playlists = []
            failed_playlists = []
            total_tracks_added = 0
            
            # Process playlists in sorted order
            for playlist_index, (original_name, tracks) in enumerate(sorted_playlists, start=1):
                if not tracks:
                    logging.warning(f"No tracks found for '{original_name}'. Skipping.")
                    failed_playlists.append((original_name, "No tracks"))
                    continue
                
                # Standardize playlist names
                # Extract the genre from the original name
                genre_match = re.match(r'(.+?)(?:\sMix|\sSampler)(?:\s#\d+)?$', original_name)
                genre = genre_match.group(1) if genre_match else original_name
                
                # Format the title consistently
                is_sampler = "Sampler" in original_name
                count_match = re.search(r'#(\d+)', original_name)
                count = int(count_match.group(1)) if count_match else None
                
                # Create a new playlist name with consistent format
                if count:
                    playlist_name = f"{genre} #{count+1}"
                elif is_sampler:
                    playlist_name = f"{genre} Sampler"
                else:
                    playlist_name = f"{genre} #{count+1}"
                
                # Create custom description based on genre
                description = f"A {genre} playlist created by GenreGenius based on your music collection."
                if is_sampler:
                    description = f"A sampler of {genre} tracks created by GenreGenius based on your music collection."
                
                # Try to create and populate the playlist with proper error handling
                try:
                    logging.info(f"Creating playlist '{playlist_name}' with {len(tracks)} tracks")
                    playlist_result = self.create_playlist(playlist_name, tracks, user_id, description)
                    
                    if playlist_result:
                        playlist_url = f"https://open.spotify.com/playlist/{playlist_result}"
                        logging.info(f"SUCCESS: Created playlist: {playlist_name}")
                        logging.info(f"Playlist URL: {playlist_url}")
                        successful_playlists.append((playlist_name, len(tracks), playlist_url))
                        total_tracks_added += len(tracks)
                    else:
                        logging.error(f"Failed to create playlist '{playlist_name}'")
                        failed_playlists.append((playlist_name, "Creation failed"))
                except Exception as e:
                    logging.error(f"Error creating playlist '{playlist_name}': {e}")
                    failed_playlists.append((playlist_name, str(e)))
                    
            # Print summary of results
            logging.info("\n" + "="*60)
            logging.info(f"PLAYLIST CREATION SUMMARY:")
            logging.info(f"Successfully created {len(successful_playlists)} out of {len(sorted_playlists)} playlists")
            logging.info(f"Total tracks added: {total_tracks_added}")
            
            if successful_playlists:
                logging.info("\nSuccessful playlists:")
                for name, track_count, url in successful_playlists:
                    logging.info(f"  - {name} ({track_count} tracks): {url}")
            
            if failed_playlists:
                logging.info("\nFailed playlists:")
                for name, reason in failed_playlists:
                    logging.info(f"  - {name}: {reason}")
            
            logging.info("="*60)
                    
        except Exception as e:
            logging.error(f"Error in create_playlists_in_spotify: {e}")
            import traceback
            logging.error(traceback.format_exc())

    @backoff.on_exception(
        backoff.expo, 
        (socket.gaierror, Exception),
        max_tries=5,
        giveup=lambda e: not dns_resolve_backoff(e),
        on_backoff=backoff_hdlr
    )
    def create_playlist(self, playlist_name: str, track_ids: List[str], user_id: str, description: str = None) -> Optional[str]:
        """
        Create a playlist and add tracks to it with improved error handling.
        
        Args:
            playlist_name (str): Name of the playlist
            track_ids (List[str]): List of track IDs to add
            user_id (str): Spotify user ID
            description (str, optional): Playlist description
            
        Returns:
            Optional[str]: Playlist ID or None on failure
        """
        try:
            # First create an empty playlist
            logging.info(f"Creating empty playlist '{playlist_name}'")
            
            # If no description provided, create a generic one
            if not description:
                description = f"Playlist created by GenreGenius discovery tool"
            
            playlist = self.sp.user_playlist_create(
                user_id, 
                playlist_name, 
                public=True,
                description=description
            )
            playlist_id = playlist['id']
            
            # Log playlist details
            logging.info(f"Empty playlist created with ID: {playlist_id}")
            
            # Then add tracks to it in chunks to avoid API limits
            total_tracks = len(track_ids)
            logging.info(f"Adding {total_tracks} tracks to playlist")
            
            # Add tracks in chunks of 50
            chunk_size = 50
            tracks_added = 0
            failed_chunks = 0
            
            for i in range(0, total_tracks, chunk_size):
                chunk = track_ids[i:i+chunk_size]
                chunk_num = (i // chunk_size) + 1
                total_chunks = (total_tracks + chunk_size - 1) // chunk_size
                
                logging.info(f"Adding chunk {chunk_num}/{total_chunks} ({len(chunk)} tracks)")
                
                # Try to add the tracks with specific error handling
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries:
                    try:
                        self.sp.user_playlist_add_tracks(user_id, playlist_id, chunk)
                        tracks_added += len(chunk)
                        logging.info(f"Successfully added chunk {chunk_num}/{total_chunks} to playlist")
                        break  # Success, exit retry loop
                        
                    except SpotifyException as e:
                        retry_count += 1
                        
                        if e.http_status == 429:  # Rate limiting
                            retry_after = int(e.headers.get("Retry-After", 5))
                            logging.warning(f"Rate limit hit. Waiting {retry_after}s before retry {retry_count}/{max_retries}")
                            time.sleep(retry_after + 1)  # Add buffer
                        elif e.http_status == 401:  # Auth error
                            logging.error(f"Authentication error adding tracks. Attempting to refresh token.")
                            # Create a new client and try again
                            self.sp = self.create_spotify_client()
                            time.sleep(2)  # Brief pause
                        elif e.http_status == 404:  # Not found
                            logging.error(f"Playlist not found (404). Creation may have failed.")
                            failed_chunks += 1
                            break  # Can't recover from this
                        else:
                            logging.error(f"Spotify API error adding tracks: {e} (Status: {e.http_status})")
                            if retry_count < max_retries:
                                wait_time = 2 ** retry_count  # Exponential backoff
                                logging.info(f"Retrying in {wait_time}s...")
                                time.sleep(wait_time)
                            else:
                                logging.error(f"Failed to add chunk after {max_retries} retries")
                                failed_chunks += 1
                                break
                                
                    except Exception as e:
                        retry_count += 1
                        logging.error(f"General error adding tracks: {e}")
                        if retry_count < max_retries:
                            wait_time = 2 ** retry_count  # Exponential backoff
                            logging.info(f"Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            logging.error(f"Failed to add chunk after {max_retries} retries")
                            failed_chunks += 1
                            break
            
            # Log summary of track addition
            if failed_chunks > 0:
                logging.warning(f"Added {tracks_added}/{total_tracks} tracks to playlist. {failed_chunks} chunks failed.")
            else:
                logging.info(f"Successfully added all {tracks_added} tracks to playlist!")
            
            # For playlists with artwork capability, we could add custom artwork here
            # (Spotify doesn't currently support custom artwork via API)
            
            return playlist_id
            
        except SpotifyException as e:
            logging.error(f"Spotify API error creating playlist: {e}")
            if e.http_status == 401:
                logging.error("Authentication error. Your Spotify token may have expired or lacks sufficient permissions.")
            elif e.http_status == 403:
                logging.error("Forbidden. You don't have permission to create playlists.")
            return None
        except Exception as e:
            logging.error(f"General error creating playlist: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None


def main() -> None:
    """Main entry point for the Spotify Client application."""
    # Configure logging
    setup_logging()
    
    try:
        manager = SpotifyPlaylistManager()
        file_path = manager.select_json_file()
        if file_path:
            # Use the genre-based function
            genre_artists = manager.read_artist_genres(file_path)
            if genre_artists:
                # Add this line to explicitly signal the start of playlist generation
                logging.info(f"Starting playlist generation for {sum(len(artists) for artists in genre_artists.values())} artists across {len(genre_artists)} genres")
                manager.generate_playlists_by_genre(genre_artists)
            else:
                logging.error("No valid artists found in the JSON file.")
        else:
            logging.info("No file selected.")
    except KeyboardInterrupt:
        print("\nScript execution was interrupted by user.")
    except Exception as e:
        if "getaddrinfo failed" in str(e) or isinstance(e, socket.gaierror):
            logging.error(f"Network connectivity issue: Failed to resolve 'api.spotify.com'")
            logging.info("Please check your internet connection and try again.")
        else:
            logging.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScript execution was interrupted by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")