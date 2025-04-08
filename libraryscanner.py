"""
Library scanner module for scanning FLAC music libraries and extracting artist information.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple
from pathlib import Path
import os
from collections import Counter
from colorama import Fore, Style
from mutagen.flac import FLAC


class MusicLibraryScanner(ABC):
    """Abstract base class for music library scanners."""
    
    @abstractmethod
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library and return a list of (artist_name, count) tuples
        sorted by frequency (most frequent first).
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        pass


class FlacLibraryScanner(MusicLibraryScanner):
    """Scanner for FLAC music libraries."""
    
    def __init__(self, music_dir: str, min_artist_count: int = 1):
        """
        Initialize the FLAC library scanner.
        
        Args:
            music_dir (str): Directory containing FLAC music files
            min_artist_count (int): Minimum number of songs by an artist to include them
        """
        self.music_dir = Path(music_dir)
        self.min_artist_count = min_artist_count
    
    def scan_with_musicbrainz(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for FLAC files and extract artists,
        with enhanced handling of Various Artists compilations using MusicBrainz.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        artists = []
        processed_files = 0
        skipped_files = 0
        
        # Store compilation albums with their track artists
        compilation_albums = {}  # Maps album name to set of track artist names
        
        # Store individual files for each album to avoid scanning multiple times
        album_files = {}  # Maps album name to list of file paths
        
        # First pass: identify all albums and their artists
        for root, _, files in os.walk(self.music_dir):
            flac_files = [f for f in files if f.lower().endswith('.flac')]
            if not flac_files:
                continue
                
            for file in flac_files:
                try:
                    file_path = os.path.join(root, file)
                    
                    # Skip invalid files
                    if os.path.getsize(file_path) < 128:
                        skipped_files += 1
                        continue
                        
                    # Read the FLAC file
                    flac_file = FLAC(file_path)
                    processed_files += 1
                    
                    # Extract album name from tags
                    album_name = "Unknown Album"
                    if 'album' in flac_file:
                        album_name = flac_file['album'][0]
                    
                    # Add file to album_files for later processing
                    if album_name not in album_files:
                        album_files[album_name] = []
                    album_files[album_name].append(file_path)
                    
                    # Check if this is a compilation track
                    is_compilation = False
                    
                    # Check artist tag for Various Artists indicators
                    if 'artist' in flac_file:
                        for artist in flac_file['artist']:
                            if artist.lower() in ('various artists', 'various', 'va', 'v.a.'):
                                is_compilation = True
                                break
                    
                    # Also check albumartist tag
                    if not is_compilation and 'albumartist' in flac_file:
                        for artist in flac_file['albumartist']:
                            if artist.lower() in ('various artists', 'various', 'va', 'v.a.'):
                                is_compilation = True
                                break
                    
                    # Check if the path contains "Various Artists"
                    if not is_compilation and "various artists" in root.lower():
                        is_compilation = True
                    
                    # If this is a compilation track, extract the track artist
                    if is_compilation:
                        # Initialize the album in our compilation tracking
                        if album_name not in compilation_albums:
                            compilation_albums[album_name] = set()
                        
                        # Try to extract artist from track tags
                        track_artist = None
                        
                        # First try the regular artist tag
                        if 'artist' in flac_file:
                            for artist in flac_file['artist']:
                                if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                    track_artist = artist
                                    break
                        
                        # If no artist found, try other tags
                        if not track_artist:
                            for tag in ['performer', 'composer']:
                                if tag in flac_file:
                                    for artist in flac_file[tag]:
                                        if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                            track_artist = artist
                                            break
                                    if track_artist:
                                        break
                        
                        # Try to extract from title if in "Artist - Title" format
                        if not track_artist and 'title' in flac_file:
                            title = flac_file['title'][0]
                            if ' - ' in title:
                                potential_artist = title.split(' - ')[0].strip()
                                if potential_artist and potential_artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                    track_artist = potential_artist
                        
                        # Try the "contributing artists" field
                        if not track_artist and 'Contributing artists' in flac_file:
                            track_artist = flac_file['Contributing artists'][0]
                        
                        # If we found an artist, add it
                        if track_artist:
                            artists.append(track_artist)
                            compilation_albums[album_name].add(track_artist)
                    else:
                        # Regular track, add the artist
                        if 'artist' in flac_file:
                            for artist in flac_file['artist']:
                                if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                    artists.append(artist)
                
                except Exception as e:
                    skipped_files += 1
                    if "not a valid FLAC file" not in str(e):
                        print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
        
        # Second pass: Use MusicBrainz for compilations with missing artists
        try:
            # Initialize MusicBrainz API
            from musicbrainz import MusicBrainzAPI
            mb_api = MusicBrainzAPI()
            
            # Process each compilation album
            for album_name, track_artists in compilation_albums.items():
                # Skip albums where we already have artists
                if track_artists:
                    print(f"{Fore.GREEN}Album '{album_name}' already has {len(track_artists)} artists from file tags{Style.RESET_ALL}")
                    continue
                    
                print(f"{Fore.YELLOW}Album '{album_name}' has no artists from tags, using MusicBrainz lookup{Style.RESET_ALL}")
                
                # Use MusicBrainz to look up album artists
                mb_artists = mb_api.get_album_artists(album_name)
                
                # Add the artists to our lists
                for artist in mb_artists:
                    if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                        artists.append(artist)
                        track_artists.add(artist)
                
                print(f"{Fore.GREEN}Added {len(mb_artists)} artists from MusicBrainz for album '{album_name}'{Style.RESET_ALL}")
                
                # Respect API rate limits
                time.sleep(2)
                    
        except Exception as e:
            print(f"{Fore.RED}Error using MusicBrainz: {e}{Style.RESET_ALL}")
        
        # Count occurrences of each artist and sort by frequency
        artist_counter = Counter(artists)
        
        # Filter out Various Artists entries and other common compilation placeholders
        for va in ('various artists', 'various', 'va', 'v.a.', 'soundtrack', 'original soundtrack'):
            if va in artist_counter:
                del artist_counter[va]
        
        # Filter to include only artists with at least min_artist_count songs
        filtered_artists = {artist: count for artist, count in artist_counter.items() 
                           if count >= self.min_artist_count}
        
        sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)
        
        print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid FLAC files.{Style.RESET_ALL}")
        
        if sorted_artists:
            # Show sample artists for validation
            print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
            
            print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")
        
        if skipped_files > 0:
            print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
            
        # Store compilation albums for later use
        self.compilation_albums = compilation_albums
        
        print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
        return sorted_artists
    
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for FLAC files and extract artists.
        Enhanced with MusicBrainz lookup for Various Artists compilations.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        artists = []
        processed_files = 0
        skipped_files = 0
        various_artists_albums = {}  # Changed to dict to store album name
        
        # Initialize MusicBrainz API for album lookups
        try:
            from musicbrainz import MusicBrainzAPI
            mb_api = MusicBrainzAPI()
            musicbrainz_available = True
            print(f"{Fore.GREEN}MusicBrainz API initialized for album lookups{Style.RESET_ALL}")
        except Exception as e:
            musicbrainz_available = False
            print(f"{Fore.YELLOW}MusicBrainz API not available: {e}. Various Artists processing will use file tags only.{Style.RESET_ALL}")
        
        try:
            # First pass: identify Various Artists compilations and store album names
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
                if not flac_files:
                    continue
                    
                for file in flac_files:
                    try:
                        file_path = os.path.join(root, file)
                        flac_file = FLAC(file_path)
                        
                        # Check if it's a Various Artists album
                        if 'artist' in flac_file:
                            for artist in flac_file['artist']:
                                if artist.lower() in ('various artists', 'various', 'va', 'v.a.'):
                                    # Extract album name if available
                                    album_name = flac_file.get('album', ['Unknown Album'])[0]
                                    various_artists_albums[root] = album_name
                                    print(f"{Fore.CYAN}Found Various Artists album: {album_name} in {root}{Style.RESET_ALL}")
                                    break
                    except Exception:
                        pass

            # Store MusicBrainz lookup results to avoid repeated API calls
            album_artists_cache = {}

            # Second pass: extract actual artists
            for root, _, files in os.walk(self.music_dir):
                for file in files:
                    if file.lower().endswith('.flac'):
                        try:
                            file_path = os.path.join(root, file)
                            # Check if it's a valid FLAC file before attempting to read
                            if os.path.getsize(file_path) < 128:  # Minimum valid FLAC size
                                skipped_files += 1
                                continue
                                    
                            flac_file = FLAC(file_path)
                            processed_files += 1
                            
                            # Handle "Various Artists" compilations specially
                            if root in various_artists_albums:
                                album_name = various_artists_albums[root]
                                extracted = False
                                
                                # Try different tags for artist information first
                                for tag in ['artist', 'albumartist', 'performer']:
                                    if tag in flac_file:
                                        for artist in flac_file[tag]:
                                            if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                                artists.append(artist)
                                                extracted = True
                                
                                # If no artist from tags, try composer
                                if not extracted and 'composer' in flac_file:
                                    for composer in flac_file['composer']:
                                        artists.append(composer)
                                        extracted = True
                                
                                # If still no artist and MusicBrainz is available, use album lookup
                                if not extracted and musicbrainz_available:
                                    # Use cached results if available
                                    if album_name not in album_artists_cache:
                                        # Get track artists from MusicBrainz
                                        mb_artists = mb_api.get_album_artists(album_name)
                                        album_artists_cache[album_name] = mb_artists
                                        
                                        # Log the lookup
                                        print(f"{Fore.MAGENTA}MusicBrainz lookup for '{album_name}' found {len(mb_artists)} artists{Style.RESET_ALL}")
                                        
                                    # Add all artists from the album to our list
                                    for mb_artist in album_artists_cache[album_name]:
                                        artists.append(mb_artist)
                                        extracted = True
                            else:
                                # Normal case - just use the artist tag
                                if 'artist' in flac_file:
                                    for artist in flac_file['artist']:
                                        if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                            artists.append(artist)
                        except Exception as e:
                            skipped_files += 1
                            # Only print error for unexpected issues
                            if "not a valid FLAC file" not in str(e):
                                print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error scanning directory: {e}{Style.RESET_ALL}")
        
        # Count occurrences of each artist and sort by frequency
        artist_counter = Counter(artists)
        
        # Filter out Various Artists entries and other common compilation placeholders
        for va in ('various artists', 'various', 'va', 'v.a.', 'soundtrack', 'original soundtrack'):
            if va in artist_counter:
                del artist_counter[va]
        
        # Filter to include only artists with at least min_artist_count songs
        filtered_artists = {artist: count for artist, count in artist_counter.items() 
                           if count >= self.min_artist_count}
        
        sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)
        
        print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid FLAC files.{Style.RESET_ALL}")
        
        if sorted_artists:
            # Show sample artists for validation
            print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
            
            print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")
        
        if skipped_files > 0:
            print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
            
        print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
        return sorted_artists


class ProgressTrackingFlacScanner(FlacLibraryScanner):
    """Extended FlacLibraryScanner with detailed progress tracking."""
    
    def __init__(self, music_dir: str, min_artist_count: int = 1):
        """
        Initialize the FLAC library scanner with progress tracking.
        
        Args:
            music_dir (str): Directory containing FLAC music files
            min_artist_count (int): Minimum number of songs by an artist to include them
        """
        super().__init__(music_dir, min_artist_count)
        self.total_subdirs = 0
        self.processed_subdirs = 0
        self.total_artist_dirs = 0
    
    def count_artist_directories(self) -> int:
        """
        Count the total number of subdirectories that might contain artist albums.
        
        Returns:
            int: Number of subdirectories
        """
        print(f"{Fore.CYAN}Counting artist directories in {self.music_dir}...{Style.RESET_ALL}")
        
        # Simple approach: count directories that contain FLAC files
        artist_dirs = set()
        total_subdirs = 0
        
        for root, _, files in os.walk(self.music_dir):
            # Convert to relative path from music_dir
            rel_path = os.path.relpath(root, self.music_dir)
            
            # Skip the root directory
            if rel_path == '.':
                continue
                
            # Count directories based on path depth
            # Typical structure: music_dir/artist/album
            path_parts = rel_path.split(os.sep)
            
            # First level directories are assumed to be artist directories
            if len(path_parts) == 1:
                artist_dirs.add(rel_path)
            
            # Count directories that might contain FLAC files (potential albums)
            if any(f.lower().endswith('.flac') for f in files):
                total_subdirs += 1
        
        self.total_artist_dirs = len(artist_dirs)
        self.total_subdirs = max(total_subdirs, 1)  # Avoid division by zero
        
        print(f"{Fore.GREEN}Found {self.total_artist_dirs} artist directories with {self.total_subdirs} potential album directories{Style.RESET_ALL}")
        return self.total_subdirs
    
    def scan(self) -> List[Tuple[str, int]]:
        """
        Scan the music library for FLAC files and extract artists with progress reporting.
        
        Returns:
            List[Tuple[str, int]]: List of (artist_name, count) tuples
        """
        print(f"{Fore.CYAN}Scanning music library in {self.music_dir}...{Style.RESET_ALL}")
        
        # Count directories first
        self.count_artist_directories()
        
        artists = []
        processed_files = 0
        skipped_files = 0
        self.processed_subdirs = 0
        processed_dirs = set()
        various_artists_albums = set()
        
        try:
            # First pass: identify Various Artists compilations
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
                if flac_files:
                    # Track progress by counting directories with FLAC files
                    rel_dir = os.path.relpath(root, str(self.music_dir))
                    if rel_dir not in processed_dirs:
                        processed_dirs.add(rel_dir)
                        self.processed_subdirs += 1
                        
                        # Report progress as percentage
                        progress_percent = (self.processed_subdirs / self.total_subdirs) * 100
                        print(f"Progress: {progress_percent:.1f}% ({self.processed_subdirs}/{self.total_subdirs} directories)")
                
                for file in flac_files:
                    try:
                        file_path = os.path.join(root, file)
                        flac_file = FLAC(file_path)
                        
                        if 'artist' in flac_file:
                            for artist in flac_file['artist']:
                                if artist.lower() in ('various artists', 'various', 'va', 'v.a.'):
                                    various_artists_albums.add(root)
                                    break
                    except Exception:
                        pass

            # Reset progress counter for second pass
            self.processed_subdirs = 0
            processed_dirs.clear()

            # Second pass: extract actual artists
            for root, _, files in os.walk(self.music_dir):
                flac_files = [f for f in files if f.lower().endswith('.flac')]
                
                if flac_files:
                    # Track progress by counting directories with FLAC files
                    rel_dir = os.path.relpath(root, str(self.music_dir))
                    if rel_dir not in processed_dirs:
                        processed_dirs.add(rel_dir)
                        self.processed_subdirs += 1
                        
                        # Report progress as percentage
                        progress_percent = (self.processed_subdirs / self.total_subdirs) * 100
                        print(f"Progress: {progress_percent:.1f}% ({self.processed_subdirs}/{self.total_subdirs} directories)")
                
                for file in files:
                    if file.lower().endswith('.flac'):
                        try:
                            file_path = os.path.join(root, file)
                            # Check if it's a valid FLAC file before attempting to read
                            if os.path.getsize(file_path) < 128:  # Minimum valid FLAC size
                                skipped_files += 1
                                continue
                                
                            flac_file = FLAC(file_path)
                            processed_files += 1
                            
                            # Handle "Various Artists" compilations specially
                            if root in various_artists_albums:
                                # For compilations, get artists from individual tracks
                                extracted = False
                                
                                # Try different tags for artist information
                                for tag in ['artist', 'albumartist', 'performer']:
                                    if tag in flac_file:
                                        for artist in flac_file[tag]:
                                            if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                                artists.append(artist)
                                                extracted = True
                                                
                                # Try composer if no other artist was found
                                if not extracted and 'composer' in flac_file:
                                    for composer in flac_file['composer']:
                                        artists.append(composer)
                            else:
                                # Normal case - just use the artist tag
                                if 'artist' in flac_file:
                                    for artist in flac_file['artist']:
                                        if artist.lower() not in ('various artists', 'various', 'va', 'v.a.'):
                                            artists.append(artist)
                        except Exception as e:
                            skipped_files += 1
                            # Only print error for unexpected issues
                            if "not a valid FLAC file" not in str(e):
                                print(f"{Fore.RED}Error processing {file}: {e}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error scanning directory: {e}{Style.RESET_ALL}")
        
        # Report final progress
        print(f"Progress: 100.0% ({self.total_subdirs}/{self.total_subdirs} directories)")
        
        # Count occurrences of each artist and sort by frequency
        artist_counter = Counter(artists)
        
        # Filter out Various Artists entries and other common compilation placeholders
        for va in ('various artists', 'various', 'va', 'v.a.', 'soundtrack', 'original soundtrack'):
            if va in artist_counter:
                del artist_counter[va]
        
        # Filter to include only artists with at least min_artist_count songs
        filtered_artists = {artist: count for artist, count in artist_counter.items() 
                           if count >= self.min_artist_count}
        
        sorted_artists = sorted(filtered_artists.items(), key=lambda x: x[1], reverse=True)
        
        print(f"{Fore.GREEN}Found {len(sorted_artists)} unique artists in {processed_files} valid FLAC files.{Style.RESET_ALL}")
        
        if sorted_artists:
            # Show sample artists for validation
            print(f"{Fore.GREEN}Sample artists in library: {', '.join([a[0] for a in sorted_artists[:5]])}{Style.RESET_ALL}")
            
            print(f"{Fore.GREEN}Top 10 artists: {', '.join([a[0] for a in sorted_artists[:10]])}{Style.RESET_ALL}")
        
        if skipped_files > 0:
            print(f"{Fore.YELLOW}Skipped {skipped_files} invalid or problematic files.{Style.RESET_ALL}")
            
        print(f"{Fore.GREEN}Returning all {len(sorted_artists)} artists{Style.RESET_ALL}")
        return sorted_artists