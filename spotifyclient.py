"""
Spotify Client module for creating playlists based on artist recommendations.
"""

import json
import time
import sys
import os
import socket
import logging
import io
import random
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

import backoff
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
        Open a file dialog to select the source JSON file.
        
        Returns:
            str: Selected file path or empty string if canceled
        """
        logging.info("Please select the source JSON file.")
        root = Tk()
        root.withdraw()
        file_path = askopenfilename(filetypes=[("JSON files", "*.json")])
        root.destroy()
        return file_path

    def get_artist_genre(self, artist_name: str) -> Tuple[str, List[str]]:
        """
        Get the primary genre and all genres for an artist using MusicBrainz API.
        
        Args:
            artist_name (str): Name of the artist
            
        Returns:
            Tuple[str, List[str]]: (Primary genre, All genres) or ("Miscellaneous", []) if not found
        """
        # Check cache first
        if artist_name in self.artist_genre_cache:
            return self.artist_genre_cache[artist_name]
        
        # ALWAYS enforce strict 2-second delay between MusicBrainz requests
        current_time = time.time()
        time_since_last_request = current_time - self.last_mb_request_time
        if time_since_last_request < 2.0:
            sleep_time = 2.0 - time_since_last_request
            logging.info(f"Pausing for {sleep_time:.2f}s to respect MusicBrainz rate limit")
            time.sleep(sleep_time)
        
        # Search for artist
        logging.info(f"Searching MusicBrainz for artist: {artist_name}")
        try:
            artist = self.mb.search_artist(artist_name)
            self.last_mb_request_time = time.time()  # Update last request time
            
            if not artist:
                logging.warning(f"Artist '{artist_name}' not found in MusicBrainz")
                self.artist_genre_cache[artist_name] = ("Miscellaneous", [])
                return ("Miscellaneous", [])
            
            # ALWAYS enforce strict 2-second delay for the next request
            current_time = time.time()
            time_since_last_request = current_time - self.last_mb_request_time
            if time_since_last_request < 2.0:
                sleep_time = 2.0 - time_since_last_request
                logging.info(f"Pausing for {sleep_time:.2f}s to respect MusicBrainz rate limit")
                time.sleep(sleep_time)
            
            # Get genres for artist
            genres = self.mb.get_artist_genres(artist['id'])
            self.last_mb_request_time = time.time()  # Update last request time
            
            if not genres:
                logging.warning(f"No genres found for '{artist_name}'")
                self.artist_genre_cache[artist_name] = ("Miscellaneous", [])
                return ("Miscellaneous", [])
            
            # Clean and normalize genres
            cleaned_genres = [g.title().strip() for g in genres if g.strip()]
            
            # Use the first genre as primary
            primary_genre = cleaned_genres[0]
            logging.info(f"Found genres for '{artist_name}': Primary: {primary_genre}, All: {cleaned_genres}")
            
            # Cache the result
            self.artist_genre_cache[artist_name] = (primary_genre, cleaned_genres)
            return (primary_genre, cleaned_genres)
            
        except Exception as e:
            logging.error(f"Error getting genres for '{artist_name}': {e}")
            self.artist_genre_cache[artist_name] = ("Miscellaneous", [])
            return ("Miscellaneous", [])

    def read_artist_genres(self, filename: str) -> defaultdict:
        """
        Read artists from JSON file and organize by genre - FIXED VERSION.
        Only processes the INSPIRED artists (values) from the JSON, not the key artists.
        
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
            
            # Collect all unique inspired artists to process
            all_inspired_artists = []
            for key_artist, inspired_artists in data.items():
                all_inspired_artists.extend(inspired_artists)
            
            # Remove duplicates while preserving order
            unique_inspired_artists = []
            seen = set()
            for artist in all_inspired_artists:
                if artist not in seen:
                    seen.add(artist)
                    unique_inspired_artists.append(artist)
            
            # Store total count for progress tracking
            self.total_keys = len(unique_inspired_artists)
            self.processed_keys = 0
            
            # Log total artists for progress tracking
            logging.info(f"JSON file contains {self.total_keys} total inspired artists to process")
            
            # Process only the inspired artists from the JSON values
            for artist in unique_inspired_artists:
                # Get genre for the inspired artist
                primary_genre, all_genres = self.get_artist_genre(artist)
                
                # Add the inspired artist to its primary genre
                if artist not in genre_artists[primary_genre]:
                    genre_artists[primary_genre].append(artist)
                
                # Update processed count and log progress
                self.processed_keys += 1
                progress_percent = (self.processed_keys / self.total_keys) * 100
                logging.info(f"Progress: {progress_percent:.1f}% ({self.processed_keys}/{self.total_keys} artists)")
            
            # Log summary of genres and artists
            total_artists = sum(len(artists) for artists in genre_artists.values())
            logging.info(f"Found {len(genre_artists)} genres with {total_artists} total artists")
            for genre, artists in genre_artists.items():
                logging.info(f"Genre '{genre}': {len(artists)} artists")
            
            return genre_artists
        except Exception as e:
            logging.error(f"Error reading JSON file: {e}")
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
        Get genres for a track and check if it matches the target genre.
        Uses improved genre classification without hardcoding artists.
        
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
                          'industrial rock', 'industrial', 'post-punk', 'new wave'}
                          
        electronic_signifiers = {'electronic', 'techno', 'house', 'trance', 'edm', 'electronica', 
                               'ambient', 'downtempo', 'idm', 'drum and bass', 'dubstep'}
        
        # Count the number of strong genre signifiers
        rock_matches = len(all_genres.intersection(rock_signifiers))
        electronic_matches = len(all_genres.intersection(electronic_signifiers))
        
        # If there's a genre conflict (both rock and electronic elements),
        # bias toward rock classification if rock signifiers are stronger
        if rock_matches > 0 and electronic_matches > 0:
            if rock_matches >= electronic_matches and target_lower == 'rock':
                # This is primarily a rock artist appearing in rock playlist
                return (True, 1.0, genre_list)
            elif rock_matches > electronic_matches and target_lower == 'electronic':
                # This is primarily a rock artist wrongly in electronic playlist
                return (False, 0.2, genre_list)
            elif electronic_matches > rock_matches and target_lower == 'electronic':
                # This is primarily an electronic artist in electronic playlist
                return (True, 1.0, genre_list)
            elif electronic_matches >= rock_matches and target_lower == 'rock':
                # This is primarily an electronic artist wrongly in rock playlist
                return (False, 0.2, genre_list)
        
        # Calculate match score (0.0 to 1.0) for normal cases
        match_score = 0.0
        
        # Direct match with target genre
        if target_lower in all_genres:
            match_score = 1.0
        else:
            # Check for genre compatibility - imperfect matches
            # These are common genre groupings that are related
            genre_groups = {
                'rock': ['alternative', 'indie', 'punk', 'metal', 'hard rock', 'classic rock', 
                        'progressive rock', 'art rock', 'industrial rock', 'industrial', 
                        'alternative rock', 'post-punk', 'grunge', 'new wave'],
                'pop': ['dance pop', 'synth pop', 'indie pop', 'electropop', 'pop rock'],
                'jazz': ['bebop', 'swing', 'fusion', 'blues', 'soul', 'funk'],
                'metal': ['heavy metal', 'thrash', 'death metal', 'black metal', 'rock', 
                         'progressive metal', 'doom metal', 'metalcore'],
                'electronic': ['techno', 'house', 'trance', 'edm', 'dance', 'ambient', 'dubstep',
                              'electronica', 'downtempo', 'idm', 'drum and bass'],
                'classical': ['baroque', 'romantic', 'contemporary classical', 'orchestral'],
                'folk': ['acoustic', 'singer-songwriter', 'americana', 'country'],
                'hip hop': ['rap', 'trap', 'r&b', 'urban'],
                'indie': ['indie rock', 'indie pop', 'alternative'],
                'country': ['folk', 'americana', 'bluegrass'],
                'punk': ['hardcore', 'pop punk', 'post-punk', 'rock'],
                'dance': ['electronic', 'house', 'techno', 'edm', 'disco'],
                'r&b': ['soul', 'funk', 'hip hop', 'urban'],
                'aor': ['rock', 'classic rock', 'arena rock', 'hard rock']
            }
            
            # Check if target genre is in our groups
            if target_lower in genre_groups:
                related_genres = genre_groups[target_lower]
                # Check if any of track's genres are in the related genres for target
                matches = [g for g in all_genres if g in related_genres]
                if matches:
                    # Score is higher when more related genres match
                    match_score = min(0.8, 0.5 + (len(matches) * 0.1))
            
            # Check if any of track's genres have the target as a substring
            substring_matches = [g for g in all_genres if target_lower in g]
            if substring_matches:
                # Use the best score from either method
                substring_score = min(0.7, 0.4 + (len(substring_matches) * 0.1))
                match_score = max(match_score, substring_score)
        
        # Return match result, score, and all genres
        matches_target = match_score >= 0.5  # We consider 0.5 and higher a "match"
        return (matches_target, match_score, genre_list)

    def get_simplified_track_match(self, artist_tuple: Tuple[str, List[str]], target_genre: str) -> Tuple[bool, float]:
        """
        Simplified method to match an artist against a target genre using only cached genre info.
        
        Args:
            artist_tuple (Tuple[str, List[str]]): Tuple containing (artist_name, artist_genres)
            target_genre (str): Target genre to match against
            
        Returns:
            Tuple[bool, float]: (Matches target, Match score)
        """
        _, artist_genres = artist_tuple
        
        # Convert everything to lowercase for comparison
        artist_genres_lower = [g.lower() for g in artist_genres]
        target_lower = target_genre.lower()
        
        # Direct match case
        if target_lower in artist_genres_lower:
            return (True, 1.0)
        
        # Check for related genres
        genre_groups = {
            'rock': ['alternative', 'indie', 'punk', 'metal', 'hard rock', 'classic rock', 
                    'progressive rock', 'art rock', 'industrial rock', 'industrial', 
                    'alternative rock', 'post-punk', 'grunge', 'new wave'],
            'pop': ['dance pop', 'synth pop', 'indie pop', 'electropop', 'pop rock'],
            'jazz': ['bebop', 'swing', 'fusion', 'blues', 'soul', 'funk'],
            'metal': ['heavy metal', 'thrash', 'death metal', 'black metal', 'rock', 
                     'progressive metal', 'doom metal', 'metalcore'],
            'electronic': ['techno', 'house', 'trance', 'edm', 'dance', 'ambient', 'dubstep',
                          'electronica', 'downtempo', 'idm', 'drum and bass'],
            'classical': ['baroque', 'romantic', 'contemporary classical', 'orchestral'],
            'folk': ['acoustic', 'singer-songwriter', 'americana', 'country'],
            'hip hop': ['rap', 'trap', 'r&b', 'urban'],
            'indie': ['indie rock', 'indie pop', 'alternative'],
            'country': ['folk', 'americana', 'bluegrass'],
            'punk': ['hardcore', 'pop punk', 'post-punk', 'rock'],
            'dance': ['electronic', 'house', 'techno', 'edm', 'disco'],
            'r&b': ['soul', 'funk', 'hip hop', 'urban'],
            'aor': ['rock', 'classic rock', 'arena rock', 'hard rock']
        }
        
        # Check if target genre is in our groups
        score = 0.0
        if target_lower in genre_groups:
            related_genres = genre_groups[target_lower]
            # Check if any of artist's genres are in the related genres for target
            matches = [g for g in artist_genres_lower if g in related_genres]
            if matches:
                # Score is higher when more related genres match
                score = min(0.8, 0.5 + (len(matches) * 0.1))
        
        # Check if any of artist's genres have the target as a substring
        substring_matches = [g for g in artist_genres_lower if target_lower in g]
        if substring_matches:
            # Use the best score from either method
            substring_score = min(0.7, 0.4 + (len(substring_matches) * 0.1))
            score = max(score, substring_score)
        
        # Return match result and score
        return (score >= 0.5, score)  # Consider 0.5 and higher a "match"

    def organise_artist_tracks(self, artist: str, target_genre: str) -> List[Tuple[str, float]]:
        """
        Get genre-appropriate tracks for an artist using genre information to help with search.
        FIXED: Only looks up the artist name itself, not related artists.
        
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
        
        # For major artists, use genre to help with search
        if is_major_artist:
            # Find most relevant genre to include in search
            search_genre = None
            candidate_genres = [
                "rock", "prog rock", "progressive rock", "metal", "classic rock",
                "pop", "r&b", "hip hop", "rap", "jazz", "electronic", "dance"
            ]
            
            for genre in candidate_genres:
                if any(genre in g for g in artist_genres_lower):
                    search_genre = genre
                    break
                    
            if search_genre:
                # Try to search with both artist name and genre
                genre_query = f'artist:"{artist}" genre:"{search_genre}"'
                logging.info(f"Searching with genre context: {genre_query}")
                genre_results = self.retry_on_rate_limit(self.sp.search, q=genre_query, type='artist', limit=10)
                
                if genre_results and 'artists' in genre_results and genre_results['artists']['items']:
                    search_results = genre_results['artists']['items']
                    logging.info(f"Found {len(search_results)} results using genre-based search")
                else:
                    # Fall back to regular search
                    quoted_query = f'artist:"{artist}"'
                    quoted_results = self.retry_on_rate_limit(self.sp.search, q=quoted_query, type='artist', limit=10)
                    search_results = quoted_results.get('artists', {}).get('items', []) if quoted_results else []
            else:
                # No relevant genre found, use regular search
                quoted_query = f'artist:"{artist}"'
                quoted_results = self.retry_on_rate_limit(self.sp.search, q=quoted_query, type='artist', limit=10)
                search_results = quoted_results.get('artists', {}).get('items', []) if quoted_results else []
        else:
            # Not a major artist or no genre info, use regular search
            quoted_query = f'artist:"{artist}"'
            quoted_results = self.retry_on_rate_limit(self.sp.search, q=quoted_query, type='artist', limit=10)
            search_results = quoted_results.get('artists', {}).get('items', []) if quoted_results else []
        
        # If no results, try a broader search
        if not search_results:
            broader_query = artist  # Just the artist name without quotes
            broader_results = self.retry_on_rate_limit(self.sp.search, q=broader_query, type='artist', limit=20)
            search_results = broader_results.get('artists', {}).get('items', []) if broader_results else []
        
        if not search_results:
            logging.warning(f"No Spotify artists found for '{artist}'")
            return []
        
        # Find the best match using multiple criteria
        artist_lower = artist.lower()
        target_genre_lower = target_genre.lower()
        genre_match_candidates = []
        exact_matches = []
        best_match = None
        
        for result in search_results:
            result_name = result.get('name', '')
            result_lower = result_name.lower()
            popularity = result.get('popularity', 0)
            result_genres = [g.lower() for g in result.get('genres', [])]
            
            # Does this artist match our target genre?
            genre_match = any(target_genre_lower in g for g in result_genres)
            
            # Exact name match
            exact_name_match = (result_lower == artist_lower)
            
            # Rank by match quality
            if exact_name_match and genre_match:
                # Perfect match - exact name and genre
                logging.info(f"Perfect match! Exact name and genre match: '{result_name}'")
                best_match = result
                break
            elif exact_name_match:
                # Exact name match, may not match genre
                exact_matches.append((result, popularity))
            elif genre_match:
                # Matches the genre but not the exact name
                genre_match_candidates.append((result, popularity))
        
        # No perfect match found; choose the best available
        if not best_match:
            if exact_matches:
                # Prefer exact name matches
                exact_matches.sort(key=lambda x: x[1], reverse=True)
                best_match = exact_matches[0][0]
                logging.info(f"Using exact name match: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
            elif genre_match_candidates:
                # Next prefer genre matches
                genre_match_candidates.sort(key=lambda x: x[1], reverse=True)
                best_match = genre_match_candidates[0][0]
                logging.warning(f"Using genre match: '{best_match['name']}' (Popularity: {best_match.get('popularity', 0)})")
            else:
                # Last resort was previously the "most popular result," but we skip that
                # to ensure we don't pick a different artist name from the JSON.
                logging.error(f"Failed to find an exact or genre match for '{artist}'")
                return []
        
        # NEW CHECK: If best_match name doesn't match exactly, abort
        # (Prevents pulling an unrelated artist.)
        if best_match and best_match['name'].lower() != artist_lower:
            logging.warning(f"Skipping '{artist}' because Spotify matched name '{best_match['name']}' instead.")
            return []
        
        artist_id = best_match['id']
        artist_name = best_match['name']
        
        # Get artist's top tracks
        top_tracks = self.retry_on_rate_limit(self.sp.artist_top_tracks, artist_id)
        
        matching_tracks = []
        all_tracks = []
        
        if top_tracks and 'tracks' in top_tracks:
            for track in top_tracks['tracks']:
                track_id = track['id']
                track_name = track['name']
                
                # MODIFIED: Only include tracks where this artist is the primary artist
                # Don't perform additional lookups for featured artists
                primary_artist = track['artists'][0] if track['artists'] else None
                if not primary_artist or primary_artist['id'] != artist_id:
                    logging.info(f"Skipping '{track_name}' as '{artist_name}' is not the primary artist")
                    continue
                
                # Check match score against target genre - using cached genre info only
                artist_tup = (artist, artist_genres)
                matches, score = self.get_simplified_track_match(artist_tup, target_genre)
                track_info = (track_id, score)
                all_tracks.append(track_info)
                
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
                # Take top 3 anyway, but artificially lower score
                top_3 = sorted(all_tracks, key=lambda x: x[1], reverse=True)[:3]
                matching_tracks = [(tid, min(s, 0.4)) for tid, s in top_3]
                logging.info(f"Using {len(matching_tracks)} best-effort tracks for '{artist_name}'")
        
        # Sort final results by match score, descending
        matching_tracks.sort(key=lambda x: x[1], reverse=True)
        
        # Return top 5
        return matching_tracks[:5]

    def generate_playlists_by_genre(self, genre_artists: Dict[str, List[str]]) -> None:
        """
        Generate playlists by genre from artist recommendations.
        - Requires minimum 50 tracks per playlist, max 75
        - Ensures tracks are randomized to avoid consecutive tracks by the same artist
        - Uses more general genre categories
        
        Args:
            genre_artists (Dict[str, List[str]]): Dictionary mapping genres to artists
        """
        # Map specific genres to more general categories
        genre_mapping = {
            # Electronic music family
            "ambient trance": "Electronic",
            "alternative dance": "Electronic",
            "dance": "Electronic",
            "trance": "Electronic",
            "progressive trance": "Electronic",
            "progressive house": "Electronic",
            "house": "Electronic",
            "techno": "Electronic",
            "edm": "Electronic",
            "electronica": "Electronic",
            "electronic": "Electronic",
            "electro house": "Electronic",
            "drum and bass": "Electronic",
            "dubstep": "Electronic",
            "ambient": "Electronic",
            "idm": "Electronic",
            "downtempo": "Electronic",
            
            # Rock music family
            "aor": "Rock",
            "arena rock": "Rock",
            "classic rock": "Rock",
            "hard rock": "Rock",
            "blues rock": "Rock",
            "rock": "Rock",
            "rock and roll": "Rock",
            "alternative rock": "Rock",
            "indie rock": "Rock",
            "pop rock": "Rock",
            "progressive rock": "Rock",
            "psychedelic rock": "Rock",
            "metal": "Rock",
            "heavy metal": "Rock",
            "glam metal": "Rock",
            
            # Pop music family
            "art pop": "Pop",
            "alternative pop": "Pop",
            "dance-pop": "Pop",
            "synth-pop": "Pop",
            "electropop": "Pop",
            "pop": "Pop",
            "contemporary r&b": "Pop",
            "r&b": "Pop",
            "europop": "Pop",
            "bubblegum pop": "Pop",
            
            # Folk/Country music family
            "americana": "Folk & Country",
            "folk": "Folk & Country",
            "country": "Folk & Country",
            "country pop": "Folk & Country",
            "bluegrass": "Folk & Country",
            "singer-songwriter": "Folk & Country",
            
            # Other categories as fallbacks
            "blues": "Blues & Jazz",
            "jazz": "Blues & Jazz",
            "soul": "Blues & Jazz",
            "funk": "Blues & Jazz",
            "fusion": "Blues & Jazz",
            
            "hip hop": "Hip Hop & Urban",
            "rap": "Hip Hop & Urban",
            "trap": "Hip Hop & Urban",
            "urban": "Hip Hop & Urban"
        }
        
        # Create a new dictionary with general genre categories
        general_genre_artists = defaultdict(list)
        
        # Reassign artists to general genres
        for specific_genre, artists in genre_artists.items():
            # Convert to lowercase for matching
            specific_genre_lower = specific_genre.lower()
            
            # Look up the general category
            general_genre = genre_mapping.get(specific_genre_lower, "Other")
            
            # Add artists to the general genre
            general_genre_artists[general_genre].extend(artists)
            
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
            
            # Check if we have enough tracks for a playlist (minimum 50)
            if total_tracks_found >= 50:
                # Create an intelligently randomized track list to avoid consecutive tracks by same artist
                genre_tracks = self.create_balanced_playlist(artist_track_mapping)
                
                logging.info(f"Created balanced playlist with {len(genre_tracks)} tracks for genre '{genre}'")
                
                # Use genre name for playlist
                playlist_name = f"{genre} Mix"
                
                # Add up to 75 tracks per playlist
                all_playlists[playlist_name] = genre_tracks[:75]
                
                # Handle additional playlists if we have a lot of tracks
                if len(genre_tracks) > 75:
                    chunks = [genre_tracks[i:i+75] for i in range(75, len(genre_tracks), 75)]
                    for i, chunk in enumerate(chunks, 1):
                        if len(chunk) >= 50:  # Each additional playlist also needs at least 50 tracks
                            all_playlists[f"{genre} Mix {i+1}"] = chunk
            else:
                logging.warning(f"Not enough tracks for genre '{genre}' (found {total_tracks_found}, need at least 50)")
                
                # If we have fewer than 50 tracks but more than 30, create a playlist anyway
                # but log a warning
                if total_tracks_found >= 30:
                    logging.info(f"Creating playlist anyway with {total_tracks_found} tracks (below minimum)")
                    
                    # Create balanced playlist with what we have
                    genre_tracks = self.create_balanced_playlist(artist_track_mapping)
                    playlist_name = f"{genre} Mix (Limited)"
                    all_playlists[playlist_name] = genre_tracks

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
        Create playlists in Spotify with the given tracks.
        
        Args:
            all_playlists (Dict[str, List[str]]): Dictionary mapping playlist names to track IDs
        """
        try:
            # Get user details and log them for debugging
            user_details = self.sp.current_user()
            user_id = user_details['id']
            logging.info(f"Creating playlists for Spotify user: {user_id} ({user_details.get('display_name', 'Unknown')})")
            
            # Log the playlists we're about to create
            logging.info(f"Attempting to create {len(all_playlists)} playlists")
            for playlist_name, tracks in all_playlists.items():
                logging.info(f"  - '{playlist_name}': {len(tracks)} tracks")
            
            # Dictionary to track number of playlists per genre
            genre_counts = {}
            
            # Process playlists
            for playlist_index, (playlist_name, tracks) in enumerate(all_playlists.items(), start=1):
                if not tracks:
                    logging.warning(f"No tracks found for '{playlist_name}'. Skipping.")
                    continue
                
                # Extract genre from playlist name
                genre = playlist_name.replace(" Mix", "").strip()
                
                # Update the count for this genre
                if genre not in genre_counts:
                    genre_counts[genre] = 1
                else:
                    genre_counts[genre] += 1
                
                # Create the numbered playlist name
                numbered_playlist_name = f"{genre} Mix #{genre_counts[genre]}"
                
                # Try to create and populate the playlist with proper error handling
                try:
                    logging.info(f"Creating playlist '{numbered_playlist_name}' with {len(tracks)} tracks")
                    playlist_result = self.create_playlist(numbered_playlist_name, tracks, user_id)
                    
                    if playlist_result:
                        playlist_url = f"https://open.spotify.com/playlist/{playlist_result}"
                        logging.info(f"SUCCESS: Created playlist: {numbered_playlist_name}")
                        logging.info(f"Playlist URL: {playlist_url}")
                    else:
                        logging.error(f"Failed to create playlist '{numbered_playlist_name}'")
                except Exception as e:
                    logging.error(f"Error creating playlist '{numbered_playlist_name}': {e}")
                    
        except Exception as e:
            logging.error(f"Error in create_playlists_in_spotify: {e}")

    @backoff.on_exception(
        backoff.expo, 
        (socket.gaierror, Exception),
        max_tries=5,
        giveup=lambda e: not dns_resolve_backoff(e),
        on_backoff=backoff_hdlr
    )
    def create_playlist(self, playlist_name: str, track_ids: List[str], user_id: str) -> Optional[str]:
        """
        Create a playlist and add tracks to it.
        
        Args:
            playlist_name (str): Name of the playlist
            track_ids (List[str]): List of track IDs to add
            user_id (str): Spotify user ID
            
        Returns:
            Optional[str]: Playlist ID or None on failure
        """
        try:
            # First create an empty playlist
            logging.info(f"Creating empty playlist '{playlist_name}'")
            playlist = self.sp.user_playlist_create(
                user_id, 
                playlist_name, 
                public=True,
                description=f"Genre playlist created by SpotifyPlaylistManager"
            )
            playlist_id = playlist['id']
            
            # Log playlist details
            logging.info(f"Empty playlist created with ID: {playlist_id}")
            
            # Then add tracks to it in chunks to avoid API limits
            total_tracks = len(track_ids)
            logging.info(f"Adding {total_tracks} tracks to playlist")
            
            # Add tracks in chunks of 50
            chunk_size = 50
            for i in range(0, total_tracks, chunk_size):
                chunk = track_ids[i:i+chunk_size]
                logging.info(f"Adding chunk of {len(chunk)} tracks (tracks {i+1}-{i+len(chunk)})")
                
                # Try to add the tracks with specific error handling
                try:
                    self.sp.user_playlist_add_tracks(user_id, playlist_id, chunk)
                    logging.info(f"Successfully added chunk to playlist")
                except SpotifyException as e:
                    logging.error(f"Spotify API error adding tracks: {e}")
                    if e.http_status == 404:
                        logging.error("Playlist not found. Creation may have failed.")
                    elif e.http_status == 401:
                        logging.error("Authentication error. Check your Spotify credentials.")
                    else:
                        logging.error(f"Status code: {e.http_status}")
                except Exception as e:
                    logging.error(f"General error adding tracks: {e}")
            
            return playlist_id
        except SpotifyException as e:
            logging.error(f"Spotify API error creating playlist: {e}")
            if e.http_status == 401:
                logging.error("Authentication error. Your Spotify token may have expired or lacks sufficient permissions.")
            return None
        except Exception as e:
            logging.error(f"General error creating playlist: {e}")
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