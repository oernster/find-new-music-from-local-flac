import json
import random
import logging
import time
import sys
import os
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from spotipy import SpotifyOAuth, Spotify
from collections import defaultdict
from colorama import init, Fore, Style, Cursor
from spotipy.exceptions import SpotifyException
# Commented out MusicBrainz import
# from musicbrainz import MusicBrainzAPI


# Initialize Colorama
init(autoreset=True)


class ProgressBar:
    def __init__(self, total, width=50, prefix='Progress:', suffix='Complete', fill='█', empty='─'):
        self.total = total
        self.width = width
        self.prefix = prefix
        self.suffix = suffix
        self.fill = fill
        self.empty = empty
        self.current = 0
        self.start_time = time.time()
        self.request_delay = 1.2  # Default delay
        self.bar_output_lines = 2  # How many lines the progress bar takes
        
        # Get terminal size
        try:
            self.terminal_height = os.get_terminal_size().lines
        except (AttributeError, OSError):
            self.terminal_height = 24  # Default fallback height
            
        # Clear the area where the progress bar will be
        sys.stdout.write("\n" * self.bar_output_lines)
        
        # Initial display
        self.display()
        
    def update(self, current=None, request_delay=None):
        """Update progress bar state"""
        if current is not None:
            self.current = current
        if request_delay is not None:
            self.request_delay = request_delay
        self.display()
        
    def increment(self):
        """Increment progress by 1"""
        self.current += 1
        self.display()
    
    def calculate_eta(self):
        """Calculate and format the estimated time to completion"""
        if self.current == 0:
            return "Calculating..."
        
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return "Calculating..."
            
        items_per_second = self.current / elapsed
        items_remaining = self.total - self.current
        
        # Factor in the request delay for remaining tasks
        remaining_seconds = items_remaining / items_per_second
        
        # Format the remaining time
        if remaining_seconds < 60:
            return f"{int(remaining_seconds)}s"
        elif remaining_seconds < 3600:
            minutes = int(remaining_seconds // 60)
            seconds = int(remaining_seconds % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(remaining_seconds // 3600)
            minutes = int((remaining_seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
    
    def display(self):
        """Display or update the progress bar at the bottom of the screen"""
        # Calculate the progress
        filled_length = int(self.width * self.current // self.total)
        bar = self.fill * filled_length + self.empty * (self.width - filled_length)
        percentage = f"{100 * self.current / self.total:.1f}%" if self.total > 0 else "0.0%"
        eta = self.calculate_eta()
        
        # Format the progress bar
        line1 = f"{Fore.CYAN}{self.prefix} |{Fore.GREEN}{bar}{Fore.CYAN}| {percentage} {self.suffix}"
        line2 = f"{Fore.CYAN}Processed: {self.current}/{self.total} artists | ETA: {eta}{Style.RESET_ALL}"
        
        # Save current cursor position
        sys.stdout.write("\033[s")
        
        # Move to the bottom of the screen minus the progress bar height
        sys.stdout.write(f"\033[{self.terminal_height-1};1H")
        
        # Clear the lines where the progress bar will be
        sys.stdout.write("\033[K" + line1 + "\n\033[K" + line2)
        
        # Restore cursor position
        sys.stdout.write("\033[u")
        
        # Ensure output is displayed
        sys.stdout.flush()
    
    def cleanup(self):
        """Clean up by moving cursor to the end"""
        sys.stdout.write(f"\033[{self.terminal_height};1H\n")
        sys.stdout.flush()


class CustomLogFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages"""
    def format(self, record):
        levelname = record.levelname
        message = super().format(record)
        
        if levelname == 'INFO':
            return f"{Fore.YELLOW}INFO: {Fore.CYAN}{record.getMessage()}{Style.RESET_ALL}"
        elif levelname == 'WARNING':
            return f"{Fore.YELLOW}WARNING: {Fore.RED}{record.getMessage()}{Style.RESET_ALL}"
        elif levelname == 'ERROR':
            return f"{Fore.YELLOW}ERROR: {Fore.RED}{record.getMessage()}{Style.RESET_ALL}"
        else:
            return message


class ProgressBarLogHandler(logging.StreamHandler):
    """Custom log handler that preserves the progress bar"""
    def __init__(self, progress_bar):
        super().__init__()
        self.progress_bar = progress_bar
        self.setFormatter(CustomLogFormatter())
        
    def emit(self, record):
        # Format the log message
        message = self.format(record)
        
        # Save cursor position
        sys.stdout.write("\033[s")
        
        # Move cursor to a position for log messages
        # First clear the area where the progress bar is (move up 2 lines from cursor)
        sys.stdout.write("\033[2A")
        
        # Clear the entire line before writing the message
        sys.stdout.write("\033[K")
        
        # Write log message and newline with line clear
        sys.stdout.write(message + "\n\033[K\n")
        
        # Restore cursor position
        sys.stdout.write("\033[u")
        
        # Redraw the progress bar
        self.progress_bar.display()
        
        # Flush to ensure everything is displayed
        sys.stdout.flush()


class SpotifyPlaylistManager:
    request_delay = 1.2  # Minimum delay between consecutive requests in seconds

    def __init__(self):
        self.progress_bar = None
        self.sp = self.create_spotify_client()
        # Commented out MusicBrainz initialization
        # self.mb_api = MusicBrainzAPI(user_email="oliverjernster@hotmail.com")
        logging.info("Spotify Authentication Successful!")


    def create_spotify_client(self):
        try:
            # Use more comprehensive scopes to ensure we have all needed permissions
            scopes = [
                "playlist-modify-public",
                "playlist-modify-private", 
                "user-library-read",
                "user-read-email",
                "user-read-private"
            ]
            
            auth_manager = SpotifyOAuth(
                client_id="<client id here>",
                client_secret="<client secret here>",
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
        except Exception as e:
            logging.error(f"Spotify Authentication Failed: {e}")
            raise

    def select_json_file(self):
        logging.info("Please select the source JSON file.")
        root = Tk()
        root.withdraw()
        file_path = askopenfilename(filetypes=[("JSON files", "*.json")])
        root.destroy()
        return file_path

    def read_artist_genres(self, filename):
        """Read artists from JSON file without using MusicBrainz API."""
        try:
            with open(filename, 'r') as file:
                data = json.load(file)
            
            # Collect all inspired artists across all keys
            all_inspired_artists = []
            for key_artist, inspired_artists in data.items():
                # Only add the values (inspired artists), not the keys (source artists)
                all_inspired_artists.extend(inspired_artists)
            
            # Remove any duplicates while preserving order
            unique_artists = []
            seen = set()
            for artist in all_inspired_artists:
                if artist not in seen:
                    seen.add(artist)
                    unique_artists.append(artist)
            
            # Group artists into playlists (approximately 50 artists per playlist)
            playlist_artists = {}
            artists_per_playlist = 50
            playlist_count = max(1, (len(unique_artists) + artists_per_playlist - 1) // artists_per_playlist)
            
            for i in range(playlist_count):
                start_idx = i * artists_per_playlist
                end_idx = min((i + 1) * artists_per_playlist, len(unique_artists))
                playlist_name = f"Playlist {i+1}"
                playlist_artists[playlist_name] = unique_artists[start_idx:end_idx]
            
            logging.info(f"Found {len(unique_artists)} unique inspired artists")
            logging.info(f"Created {len(playlist_artists)} playlists")
            
            return playlist_artists
        except Exception as e:
            logging.error(f"Error reading JSON file: {e}")
            return {}

    def retry_on_rate_limit(self, func, *args, **kwargs):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Use a clearer, non-overlapping log message
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
            except Exception as e:
                logging.error(f"General error in {func.__name__}: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    logging.info(f"Retrying ({retry_count}/{max_retries})...")
                    time.sleep(2)  # Wait before retry
                else:
                    break
        
        logging.error(f"Failed after {retry_count} retries")
        return None

    def generate_playlists_by_genre(self, playlist_artists):
        all_playlists = defaultdict(list)
        
        # Convert the data structure to be compatible with the existing code
        artist_to_playlist = {artist: playlist 
                             for playlist, artists in playlist_artists.items() 
                             for artist in artists}
        
        # Set up custom logging that works with the progress bar
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Keep track of tracks per playlist for debug mode
        debug_track_count = defaultdict(int)
        debug_artists_processed = 0
        
        # Initialize progress bar with total number of artists
        total_artists = len(artist_to_playlist)
        # Ensure we have at least one artist to process (avoid division by zero)
        if total_artists == 0:
            total_artists = 1
            
        self.progress_bar = ProgressBar(total_artists)
        
        # Set up the log handler with our progress bar
        log_handler = ProgressBarLogHandler(self.progress_bar)
        root_logger.addHandler(log_handler)

        # Process ALL artists from the JSON file
        for i, (artist, playlist) in enumerate(artist_to_playlist.items()):
            logging.info(f"Organising tracks for artist: {artist}")
            playlist, tracks = self.organise_artist_tracks(artist, playlist)
            
            if tracks:
                all_playlists[playlist].extend(tracks)
                debug_track_count[playlist] += len(tracks)
                logging.info(f"Added {len(tracks)} tracks from {artist} to '{playlist}'")
                logging.info(f"'{playlist}' now has {debug_track_count[playlist]} tracks total")
            
            debug_artists_processed += 1
            
            # Update progress bar
            self.progress_bar.update(i + 1, self.request_delay)
            
            # Update total if needed
            if i + 1 > self.progress_bar.total:
                self.progress_bar.total = i + 5  # Add extra room
        
        # Debug summary
        logging.info(f"DEBUG MODE: Processed {debug_artists_processed} artists")
        for playlist, count in debug_track_count.items():
            logging.info(f"DEBUG MODE: '{playlist}' has {count} tracks")
            
        # Ensure progress shows 100% at the end
        self.progress_bar.update(self.progress_bar.total)
        
        # Process all playlists that have any tracks
        valid_playlists = {playlist: tracks for playlist, tracks in all_playlists.items() if tracks}
        if not valid_playlists:
            logging.warning("No tracks were found for any artists")
            return
            
        logging.info(f"Creating {len(valid_playlists)} playlists")
        
        # For each playlist, limit to 100 tracks but don't require a minimum
        for playlist, tracks in valid_playlists.items():
            track_count = len(tracks)
            if track_count > 0:
                logging.info(f"Creating playlist '{playlist}' with {track_count} tracks")
                if track_count > 100:
                    logging.info(f"Limiting to 100 tracks for '{playlist}'")
                    random.shuffle(tracks)
                    valid_playlists[playlist] = tracks[:100]
                
        # Create the playlists in Spotify
        self.create_playlists_in_spotify(valid_playlists)
        
        # Clean up progress bar when finished
        if self.progress_bar:
            self.progress_bar.cleanup()

    def organise_artist_tracks(self, artist, playlist):
        artist_id = self.retry_on_rate_limit(self.sp.search, q=f'artist:{artist}', type='artist', limit=1)

        if artist_id and 'artists' in artist_id and artist_id['artists']['items']:
            artist_id = artist_id['artists']['items'][0]['id']
            tracks = self.retry_on_rate_limit(self.sp.artist_top_tracks, artist_id)
            if tracks and 'tracks' in tracks:
                track_ids = [track['id'] for track in tracks['tracks'][:5]]
                return playlist, track_ids
        return playlist, []

    def create_playlists_in_spotify(self, all_playlists):
        try:
            # Get user details and log them for debugging
            user_details = self.sp.current_user()
            user_id = user_details['id']
            logging.info(f"Creating playlists for Spotify user: {user_id} ({user_details.get('display_name', 'Unknown')})")
            
            # Log the playlists we're about to create
            logging.info(f"Attempting to create {len(all_playlists)} playlists")
            for playlist_name, tracks in all_playlists.items():
                logging.info(f"  - '{playlist_name}': {len(tracks)} tracks")

            for playlist_index, (playlist_name, tracks) in enumerate(all_playlists.items(), start=1):
                if not tracks:
                    logging.warning(f"No tracks found for '{playlist_name}'. Skipping.")
                    continue

                # Try to create and populate the playlist with proper error handling
                try:
                    logging.info(f"Creating playlist '{playlist_name}' with {len(tracks)} tracks")
                    playlist_result = self.create_playlist(playlist_name, tracks, user_id)
                    
                    if playlist_result:
                        playlist_url = f"https://open.spotify.com/playlist/{playlist_result}"
                        logging.info(f"SUCCESS: Created playlist: {playlist_name}")
                        logging.info(f"Playlist URL: {playlist_url}")
                    else:
                        logging.error(f"Failed to create playlist '{playlist_name}'")
                except Exception as e:
                    logging.error(f"Error creating playlist '{playlist_name}': {e}")
                    
        except Exception as e:
            logging.error(f"Error in create_playlists_in_spotify: {e}")

    def create_playlist(self, playlist_name, track_ids, user_id):
        try:
            # First create an empty playlist
            logging.info(f"Creating empty playlist '{playlist_name}'")
            playlist = self.sp.user_playlist_create(user_id, playlist_name, public=True, 
                                                  description="Debug playlist created by SpotifyPlaylistManager")
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
                    result = self.sp.user_playlist_add_tracks(user_id, playlist_id, chunk)
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


def main():
    # Configure basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    manager = SpotifyPlaylistManager()
    file_path = manager.select_json_file()
    if file_path:
        # Now using the modified function that doesn't use MusicBrainz
        playlist_artists = manager.read_artist_genres(file_path)
        if playlist_artists:
            manager.generate_playlists_by_genre(playlist_artists)
        else:
            logging.error("No valid artists found in the JSON file.")
    else:
        logging.info("No file selected.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Script execution was interrupted by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")