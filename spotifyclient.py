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
    musicbrainz_delay = 6.0  # Minimum delay between consecutive MusicBrainz API requests

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
            scopes = [
                "playlist-modify-public",
                "playlist-modify-private", 
                "user-library-read",
                "user-read-email",
                "user-read-private"
            ]
            
            auth_manager = SpotifyOAuth(
                client_id="insert client id",
                client_secret="insert client secret",
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

    def get_artist_genre(self, artist_name: str) -> str:
        """
        Get the primary genre for an artist using MusicBrainz API.
        
        Args:
            artist_name (str): Name of the artist
            
        Returns:
            str: Primary genre or "Miscellaneous" if not found
        """
        # Check cache first
        if artist_name in self.artist_genre_cache:
            return self.artist_genre_cache[artist_name]
        
        # Enforce rate limiting for MusicBrainz API
        current_time = time.time()
        time_since_last_request = current_time - self.last_mb_request_time
        if time_since_last_request < self.musicbrainz_delay:
            sleep_time = self.musicbrainz_delay - time_since_last_request
            logging.info(f"Pausing for {sleep_time:.2f}s to respect MusicBrainz rate limit")
            time.sleep(sleep_time)
        
        # Search for artist
        logging.info(f"Searching MusicBrainz for artist: {artist_name}")
        self.last_mb_request_time = time.time()
        artist = self.mb.search_artist(artist_name)
        
        if not artist:
            logging.warning(f"Artist '{artist_name}' not found in MusicBrainz")
            self.artist_genre_cache[artist_name] = "Miscellaneous"
            return "Miscellaneous"
        
        # Get genres for artist
        time_since_last_request = time.time() - self.last_mb_request_time
        if time_since_last_request < self.musicbrainz_delay:
            sleep_time = self.musicbrainz_delay - time_since_last_request
            logging.info(f"Pausing for {sleep_time:.2f}s to respect MusicBrainz rate limit")
            time.sleep(sleep_time)
        
        self.last_mb_request_time = time.time()
        genres = self.mb.get_artist_genres(artist['id'])
        
        if not genres:
            logging.warning(f"No genres found for '{artist_name}'")
            self.artist_genre_cache[artist_name] = "Miscellaneous"
            return "Miscellaneous"
        
        # Use the first genre as primary
        primary_genre = genres[0].title()
        logging.info(f"Found genre for '{artist_name}': {primary_genre}")
        self.artist_genre_cache[artist_name] = primary_genre
        return primary_genre

    def read_artist_genres(self, filename: str) -> defaultdict:
        """
        Read artists from JSON file and organize by genre.
        
        Args:
            filename (str): Path to the JSON file
            
        Returns:
            defaultdict: Dictionary mapping genres to lists of artists
        """
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                data = json.load(file)
            
            # Store total keys for progress calculation
            self.total_keys = len(data)
            self.processed_keys = 0
            
            # Log total keys for progress tracking
            logging.info(f"JSON file contains {self.total_keys} total artists to process")
            
            # Dictionary to map genres to artists
            genre_artists = defaultdict(list)
            
            # Process source artists and their inspired artists
            for key_artist, inspired_artists in data.items():
                # Get genre for the key artist
                genre = self.get_artist_genre(key_artist)
                
                # Add inspired artists to this genre
                for artist in inspired_artists:
                    if artist not in genre_artists[genre]:
                        genre_artists[genre].append(artist)
                
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
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Log API call
                logging.info(f"API Call: {func.__name__}")
                result = func(*args, **kwargs)
                time.sleep(self.request_delay)
                return result
            except SpotifyException as e:
                if e.http_status == 429:  # Rate limit error
                    retry_after = int(e.headers.get("Retry-After", 5))
                    logging.warning(f"Rate limit hit. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after + 1)
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
                    logging.info(f"Retrying ({retry_count}/{max_retries})...")
                    time.sleep(2)  # Wait before retry
                    continue
            except socket.gaierror as e:
                logging.error(f"Failed to resolve 'api.spotify.com': {e}")
                raise  # Let backoff handle this
            except Exception as e:
                if "getaddrinfo failed" in str(e):
                    logging.error(f"Failed to resolve 'api.spotify.com': {e}")
                    raise  # Let backoff handle this
                logging.error(f"General error in {func.__name__}: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    logging.info(f"Retrying ({retry_count}/{max_retries})...")
                    time.sleep(2)  # Wait before retry
                else:
                    break
        
        logging.error(f"Failed after {retry_count} retries")
        return None

    def generate_playlists_by_genre(self, genre_artists: Dict[str, List[str]]) -> None:
        """
        Generate playlists by genre from artist recommendations.
        
        Args:
            genre_artists (Dict[str, List[str]]): Dictionary mapping genres to artists
        """
        all_playlists = defaultdict(list)
        
        # Reset counters for playlist generation phase
        self.total_to_process = sum(len(artists) for artists in genre_artists.values())
        self.processed_count = 0
                
        # Process all artists by genre
        for genre, artists in genre_artists.items():
            logging.info(f"Processing artists in genre: {genre}")
            genre_tracks = []
            
            for artist in artists:
                logging.info(f"Organizing tracks for artist: {artist}")
                tracks = self.organise_artist_tracks(artist)
                
                if tracks:
                    genre_tracks.extend(tracks)
                
                # Update progress
                self.processed_count += 1
                progress_percent = (self.processed_count / self.total_to_process) * 100
                logging.info(f"Progress: {progress_percent:.1f}% ({self.processed_count}/{self.total_to_process} artists)")
            
            # Only add playlists with enough tracks
            if len(genre_tracks) >= 20:
                # Shuffle tracks within genre
                random.shuffle(genre_tracks)
                
                # Use genre name for playlist
                playlist_name = f"{genre} Mix"
                
                # Add up to 75 tracks per playlist
                all_playlists[playlist_name] = genre_tracks[:75]
                
                # Handle additional playlists if needed
                if len(genre_tracks) > 75:
                    chunks = [genre_tracks[i:i+75] for i in range(75, len(genre_tracks), 75)]
                    for i, chunk in enumerate(chunks, 1):
                        if len(chunk) >= 20:  # Minimum tracks threshold
                            all_playlists[f"{genre} Mix {i+1}"] = chunk
            else:
                logging.warning(f"Not enough tracks for genre '{genre}' (found {len(genre_tracks)}, need at least 20)")

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

    def organise_artist_tracks(self, artist: str) -> List[str]:
        """
        Get top tracks for an artist.
        
        Args:
            artist (str): Artist name
            
        Returns:
            List[str]: List of track IDs
        """
        artist_id = self.retry_on_rate_limit(self.sp.search, q=f'artist:{artist}', type='artist', limit=1)

        if artist_id and 'artists' in artist_id and artist_id['artists']['items']:
            artist_id = artist_id['artists']['items'][0]['id']
            tracks = self.retry_on_rate_limit(self.sp.artist_top_tracks, artist_id)
            if tracks and 'tracks' in tracks:
                track_ids = [track['id'] for track in tracks['tracks'][:5]]
                return track_ids
        return []

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